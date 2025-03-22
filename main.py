import cv2
import mediapipe as mp
import time
import uuid
from flask import Flask, Response, jsonify, request
from flask_restful import Resource, Api
from supabase import create_client, Client

app = Flask(__name__)
api_handler = Api(app)


SUPABASE_URL = "https://zckfmvabmosedzfbgumg.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inpja2ZtdmFibW9zZWR6ZmJndW1nIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDIzMTMzNDcsImV4cCI6MjA1Nzg4OTM0N30.Ungvha9yUuWU9ufDl7r2Dl4jMxBqfp-xV1n0AoWL9yQ"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

cap = None
pose_tracker = None
selected_exercise = None
counter = 0
movement_active = False
client_count = 0

class PoseEstimator:
    def __init__(self, detection_confidence=0.5, tracking_confidence=0.5):
        self.pose_model = mp.solutions.pose.Pose(min_detection_confidence=detection_confidence,
                                                 min_tracking_confidence=tracking_confidence)
        self.drawer = mp.solutions.drawing_utils
        self.landmarks = []

    def detect_pose(self, frame, draw=True):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose_model.process(rgb_frame)
        if results.pose_landmarks:
            self.landmarks = results.pose_landmarks.landmark
            if draw:
                self.drawer.draw_landmarks(frame, results.pose_landmarks, mp.solutions.pose.POSE_CONNECTIONS)
        return frame

    def extract_positions(self, frame):
        extracted = []
        if self.landmarks:
            h, w, _ = frame.shape
            for idx, lm in enumerate(self.landmarks):
                extracted.append([idx, int(lm.x * w), int(lm.y * h)])
        return extracted

def start_camera():
    global cap, pose_tracker
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(0)
        pose_tracker = PoseEstimator()

def stop_camera():
    global cap
    if cap and cap.isOpened():
        cap.release()
        cv2.destroyAllWindows()
        cap = None

@app.route('/set_exercise', methods=['POST'])
def set_exercise():
    global selected_exercise, counter, movement_active
    data = request.get_json()

    if "exercise" not in data:
        return jsonify({"error": "Exercise ID is required"}), 400

    selected_exercise = int(data["exercise"])
    counter = 0  
    movement_active = False
    
    return jsonify({"status": "Exercise set", "exercise": selected_exercise})

@app.route('/video_feed')
def video_feed():
    global client_count
    client_count += 1
    start_camera()
    
    def generate_frames():
        global counter, movement_active
        prev_time = 0
        while True:
            success, frame = cap.read()
            if not success:
                continue
            
            frame = pose_tracker.detect_pose(frame)
            positions = pose_tracker.extract_positions(frame)

            if positions and selected_exercise:
                shoulder, elbow, wrist = positions[11][2], positions[13][2], positions[15][2]

                if selected_exercise == 1 and elbow < shoulder - 20:  # Push-ups
                    if not movement_active:
                        counter += 1
                        movement_active = True
                elif selected_exercise == 1 and elbow > shoulder + 20:
                    movement_active = False

                if selected_exercise == 2 and elbow > shoulder + 20 and wrist < elbow:  # Pull-ups
                    if not movement_active:
                        counter += 1
                        movement_active = True
                elif selected_exercise == 2 and elbow < shoulder - 20:
                    movement_active = False

                if selected_exercise == 3 and wrist < elbow - 20 and elbow < shoulder - 10:  # Squats
                    if not movement_active:
                        counter += 1
                        movement_active = True
                elif selected_exercise == 3 and wrist > elbow + 10:
                    movement_active = False

                cv2.putText(frame, f'Count: {counter}', (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3)

            curr_time = time.time()
            fps = 1 / (curr_time - prev_time) if prev_time else 0
            prev_time = curr_time
            cv2.putText(frame, f'FPS: {int(fps)}', (70, 50), cv2.FONT_HERSHEY_PLAIN, 3, (255, 0, 0), 3)

            _, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    response = Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    response.call_on_close(decrease_client_count)
    return response

def decrease_client_count():
    global client_count
    client_count -= 1
    if client_count <= 0:
        stop_camera()

@app.route('/get_count')
def get_count():
    return jsonify({"exercise": selected_exercise, "count": counter})

@app.route("/")
def home():
    return "Flask and Supabase Connected!"

class ViewChallenge(Resource):
    def get(self):
        response = supabase.table("challenges").select("*").execute()
        return jsonify(response.data), 200
    
class AddChallenge(Resource):
    def post(self):
        data = request.json
        new_challenge = {
            "id": str(uuid.uuid4()),  
            "title": data.get("title"),
            "desc": data.get("desc"),
            "participation": 0,
            "userId": data.get("userId"),
            "points": data.get("points"),
            "level": data.get("level"),
            "medalId": data.get("medalId")
        }
        
        response = supabase.table("challenges").insert(new_challenge).execute()
        return jsonify({"message": "Challenge added successfully", "data": response.data}), 201

class ParticipateInChallenge(Resource):
    def post(self):
        data = request.json
        challenge_id = data.get("challengeId")
        user_id = data.get("userId")

        challenge = supabase.table("challenges").select("*").eq("id", challenge_id).execute()

        if not challenge.data:
            return jsonify({"error": "Challenge not found"}), 404
        
        new_participation = challenge.data[0]['participation'] + 1
        supabase.table("challenges").update({"participation": new_participation}).eq("id", challenge_id).execute()

        return jsonify({"message": f"User {user_id} participated in challenge {challenge_id}"}), 200

class ChallengeParticipants(Resource):
    def post(self):
        data = request.json
        challenge_id = data.get("challengeId")
        challenger_id = data.get("userId")
        challenged_id = data.get("challengedId")

        challenge = supabase.table("challenges").select("*").eq("id", challenge_id).execute()
        if not challenge.data:
            return jsonify({"error": "Challenge not found"}), 404

        return jsonify({"message": f"User {challenger_id} challenged User {challenged_id} in challenge {challenge_id}"}), 200


api_handler.add_resource(ViewChallenge, '/api/view/challenge')
api_handler.add_resource(AddChallenge, '/api/add/challenge')
api_handler.add_resource(ParticipateInChallenge, '/api/participate/in/challenge')
api_handler.add_resource(ChallengeParticipants, '/api/challenge/participate')

if __name__ == "__main__":
    app.run(debug=True)
