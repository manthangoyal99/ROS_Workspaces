#!/usr/bin/env python3
import rospy

class CleaningAutomaton:
    def __init__(self):
        # Modes: 1=APPROACH, 2=CLEAN, 3=RETREAT, 0=DONE
        self.mode_id = 1 
        self.current_mode = "APPROACH"

    def update(self, props):
        is_near_mesh = props[0]
        mesh_exists = props[1]
        new_mode = self.mode_id

        # --- MODE 1: APPROACH ---
        if self.mode_id == 1:
            if mesh_exists == 1 and is_near_mesh == 1:
                rospy.loginfo("Reached the board. Starting wipe.")
                new_mode = 2
            elif mesh_exists == 0:
                rospy.loginfo("Board is already clean! Task Complete.")
                new_mode = 3 

        # --- MODE 2: CLEAN (Wiping) ---
        elif self.mode_id == 2:
            # Transition to Retreat only when physical proximity is lost
            if is_near_mesh == 0:
                rospy.loginfo("Left the board. Retreating.")
                if mesh_exists == 1:
                    rospy.loginfo("Board still has ink! Re-approaching.")
                    new_mode = 1
                else:
                    new_mode = 3

        # --- MODE 3: RETREAT / OBSERVE ---
        elif self.mode_id == 3:
            if mesh_exists == 1:
                if is_near_mesh == 1:
                    rospy.loginfo("Already near board. Restarting wipe.")
                    new_mode = 2
                else:
                    rospy.loginfo("New ink detected! Re-approaching.")
                    new_mode = 1 

        # --- STATE CHANGE LOGIC ---
        changed = (new_mode != self.mode_id)
        if changed:
            self.mode_id = new_mode
            mode_names = {1: "APPROACH", 2: "CLEAN", 3: "DONE"}
            self.current_mode = mode_names.get(new_mode, "UNKNOWN")
            
        return self.mode_id, changed