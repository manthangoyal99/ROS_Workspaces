class PickPlaceAutomaton:
    def __init__(self):
        # We start in Approach mode
        self.current_mode = "APPROACH"
        self.mode_id = 1
        self.history = [] # To track sequence (prevent jumping back)

    def update(self, propositions):
        """
        Inputs: propositions = [near_source, near_target, is_grasped]
        Returns: (mode_id, mode_name)
        """
        n_src, grasped, n_tgt = propositions

        # --- TRANSITION LOGIC ---
        
        # 1. APPROACH -> PICK
        # If we are in Approach and get close to the bowl
        if self.current_mode == "APPROACH":
            if n_src and not grasped:
                self.set_mode("PICK", 2)
            elif grasped: 
                # Error recovery: If we somehow started holding object
                self.set_mode("TRANSPORT", 3)

        # 2. PICK -> TRANSPORT
        # If we successfully grasped the object
        elif self.current_mode == "PICK":
            if grasped:
                self.set_mode("TRANSPORT", 3)
            elif not n_src:
                # If we moved away without grasping, go back to Approach
                self.set_mode("APPROACH", 1)

        # 3. TRANSPORT -> PLACE
        # If we are holding object and reach the target
        elif self.current_mode == "TRANSPORT":
            if n_tgt and grasped:
                self.set_mode("PLACE", 4)
            elif not grasped:
                # Resilience: If object dropped, go back to start or catch?
                # For data recording, we just label it as Approach (reset)
                self.set_mode("APPROACH", 1)

        # 4. PLACE -> RETREAT
        # If we released the object at the target
        elif self.current_mode == "PLACE":
            if not grasped:
                self.set_mode("RETREAT", 5)
            elif not n_tgt:
                # Moved away without dropping? Back to Transport
                self.set_mode("TRANSPORT", 3)
        
        # 5. RETREAT (End state)
        elif self.current_mode == "RETREAT":
            # If we grasp again, restart task?
            if grasped:
                self.set_mode("TRANSPORT", 3)
            # If we go back to source, restart
            if n_src and not grasped:
                self.set_mode("PICK", 2)

        return self.mode_id, self.current_mode

    def set_mode(self, name, mid):
        if self.current_mode != name:
            print(f">>> Mode Switch: {self.current_mode} -> {name}")
            self.current_mode = name
            self.mode_id = mid

