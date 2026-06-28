import numpy as np
from scipy import linalg
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C, WhiteKernel

class GPWarper:
    def __init__(self, kernel=None, alpha=1e-10, optimizer='fmin_l_bfgs_b', 
                 n_restarts_optimizer=5, normalize_y=True):
        """
        Gaussian Process Wrapper for Policy Transportation.
        """
        # Default Kernel: Constant * RBF + WhiteKernel (Noise)
        if kernel is None:
            # Length scale 0.1 is a good starting point for manipulation
            kernel = C(1.0) * RBF(length_scale=0.1) + WhiteKernel(noise_level=1e-5)
            
        self.gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=alpha,
            optimizer=optimizer,
            n_restarts_optimizer=n_restarts_optimizer,
            normalize_y=normalize_y
        )
        
        # Internal storage for analytical derivative calculation
        self.X_train = None
        self.weights = None
        self.length_scale_val = None

    def fit(self, source_points, target_points):
        """
        Learns the residual field: f(source) = target - source
        """
        residuals = target_points - source_points
        self.gp.fit(source_points, residuals)
        
        # --- PRE-CALCULATE DATA FOR ANALYTICAL JACOBIAN ---
        self.X_train = source_points
        opt_kernel = self.gp.kernel_
        
        # 1. robustly extract length_scale from the optimized kernel
        params = opt_kernel.get_params()
        
        # Try finding length_scale in common nesting patterns
        keys_to_check = [
            'k2__length_scale',       # <--- Added for (C * RBF)
            'k1__k2__length_scale',   # (C * (C * RBF))
            'k1__length_scale',       # (RBF * C)
            'length_scale'            # (Pure RBF)
        ]
        
        extracted = False
        for k in keys_to_check:
            if k in params:
                self.length_scale_val = params[k]
                extracted = True
                break
                
        if not extracted:
            print(f"[GPWarper] WARNING: Could not find length_scale in kernel params: {params.keys()}")
            self.length_scale_val = 0.05 # Fallback
            
        print(f"[GPWarper] Optimized length_scale: {self.length_scale_val}")
        
        # 2. Compute weights: K_inv * Y
        # We re-compute K to ensure we have the exact matrix used for prediction
        K = opt_kernel(self.X_train)
        
        # Add alpha to diagonal (same as sklearn does internally)
        K[np.diag_indices_from(K)] += self.gp.alpha
        
        self.weights = linalg.solve(K, residuals, assume_a='pos')

    def predict(self, points):
        """
        Returns warped point: x' = x + GP(x)
        """
        points = np.atleast_2d(points)
        delta = self.gp.predict(points)
        return (points + delta).squeeze()

    def get_jacobian(self, x):
        """
        Computes J = I + d(Residual)/dx analytically.
        Supports both Isotropic (scalar) and Anisotropic (array) length scales.
        """
        x = np.array(x).reshape(1, -1)
        
        # 1. Difference vectors (N_train, 1, 3)
        diff = self.X_train[:, np.newaxis, :] - x[np.newaxis, :, :]
        
        # 2. Handle Anisotropic Length Scales
        l_vals = np.array(self.length_scale_val)
        if l_vals.ndim == 0 or len(l_vals) == 1:
            # Isotropic (scalar)
            l2 = l_vals**2
            scaled_diff_sq = np.sum(diff**2, axis=2).flatten() / l2
            dk_dx_factor = 1.0 / l2
        else:
            # Anisotropic (array of 3 elements)
            l2 = l_vals**2  # shape (3,)
            # dist^2 = (dx^2 / lx^2) + (dy^2 / ly^2) + (dz^2 / lz^2)
            scaled_diff_sq = np.sum((diff**2) / l2, axis=2).flatten()
            dk_dx_factor = 1.0 / l2  # shape (3,)
        
        # 3. Kernel values (RBF part)
        c_val = self.gp.kernel_.get_params().get('k1__constant_value', 1.0)
        if 'k1__k1__constant_value' in self.gp.kernel_.get_params(): 
             c_val = self.gp.kernel_.get_params()['k1__k1__constant_value']
             
        k_vals = c_val * np.exp(-0.5 * scaled_diff_sq) # (N_train,)
        
        # 4. Gradients of the kernel
        if np.isscalar(dk_dx_factor):
            coeff = k_vals[:, np.newaxis] * dk_dx_factor # (N_train, 1)
            dk_dx = coeff[:, :, np.newaxis] * diff # (N_train, 1, 3)
        else:
            coeff = k_vals[:, np.newaxis] # (N_train, 1)
            # Multiply diff by the respective 1/l^2 for each axis
            dk_dx = coeff[:, :, np.newaxis] * (diff * dk_dx_factor) # (N_train, 1, 3)
        
        # 5. Jacobian of residuals: weights.T * dk_dx
        J_res = np.einsum("no,nmd->mod", self.weights, dk_dx)[0]
        
        # 6. Total Jacobian = I + J_residual
        return np.eye(3) + J_res