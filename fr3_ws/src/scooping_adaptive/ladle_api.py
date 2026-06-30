from flask import Flask, request, jsonify
import numpy as np
import cv2
from ultralytics import YOLO

app = Flask(__name__)

# Load your perfectly trained model
# spoon_tracker = YOLO('yolo26x.pt')
model = YOLO('/mnt/extra_SSD/mrityunjoy/manthan/models2/ladle_grain_detector/weights/best.pt')

@app.route("/detect", methods=["POST"])
def detect_route():
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400

    file = request.files["image"]
    
    # Decode the incoming compressed JPEG
    img = cv2.imdecode(np.frombuffer(file.read(), np.uint8), cv2.IMREAD_COLOR)

    # --- DEBUGGING ADDITIONS ---
    # 1. Save the image to see if it looks correct (not corrupted, colors are right)
    # cv2.imwrite("debug_incoming_frame.jpg", img)
    
    # 2. Lower the confidence to 0.1 to see if it's detecting weakly, and turn verbose ON
    # tracker_results = spoon_tracker(img, classes=44, conf=0.2, verbose=False)

    # if len(tracker_results[0].boxes) == 0:
    #     return jsonify({"grains_detected": 0, "status": "No spoon in view"})
    

    # box = tracker_results[0].boxes[0].xyxy[0].cpu().numpy()
    # x1, y1, x2, y2 = map(int, box)
    # pad = 20
    # h, w, _ = img.shape
    # y1, y2 = max(0, y1 - pad), min(h, y2 + pad)
    # x1, x2 = max(0, x1 - pad), min(w, x2 + pad)

    # Crop the image using standard numpy slicing
    # cropped_spoon = img[y1:y2, x1:x2]
    # cv2.imwrite("debug_incoming_frame.jpg", cropped_spoon)
    results = model(img, conf=0.4, verbose=False)
    # ---------------------------
    # ladle_status = 1 if len(tracker_results[0].boxes) > 0 else 0
    # print(tracker_results[0].bo
    ladle_status = 1 if len(results[0].boxes) > 0 else 0
    
    return jsonify({"grains_detected": ladle_status})

if __name__ == "__main__":
    print("--- Ladle Inference API Running on Port 5000 ---")
    app.run(host="0.0.0.0", port=5000, threaded=True)