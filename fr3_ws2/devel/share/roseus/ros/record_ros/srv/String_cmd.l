;; Auto-generated. Do not edit!


(when (boundp 'record_ros::String_cmd)
  (if (not (find-package "RECORD_ROS"))
    (make-package "RECORD_ROS"))
  (shadow 'String_cmd (find-package "RECORD_ROS")))
(unless (find-package "RECORD_ROS::STRING_CMD")
  (make-package "RECORD_ROS::STRING_CMD"))
(unless (find-package "RECORD_ROS::STRING_CMDREQUEST")
  (make-package "RECORD_ROS::STRING_CMDREQUEST"))
(unless (find-package "RECORD_ROS::STRING_CMDRESPONSE")
  (make-package "RECORD_ROS::STRING_CMDRESPONSE"))

(in-package "ROS")





(defclass record_ros::String_cmdRequest
  :super ros::object
  :slots (_cmd ))

(defmethod record_ros::String_cmdRequest
  (:init
   (&key
    ((:cmd __cmd) "")
    )
   (send-super :init)
   (setq _cmd (string __cmd))
   self)
  (:cmd
   (&optional __cmd)
   (if __cmd (setq _cmd __cmd)) _cmd)
  (:serialization-length
   ()
   (+
    ;; string _cmd
    4 (length _cmd)
    ))
  (:serialize
   (&optional strm)
   (let ((s (if strm strm
              (make-string-output-stream (send self :serialization-length)))))
     ;; string _cmd
       (write-long (length _cmd) s) (princ _cmd s)
     ;;
     (if (null strm) (get-output-stream-string s))))
  (:deserialize
   (buf &optional (ptr- 0))
   ;; string _cmd
     (let (n) (setq n (sys::peek buf ptr- :integer)) (incf ptr- 4) (setq _cmd (subseq buf ptr- (+ ptr- n))) (incf ptr- n))
   ;;
   self)
  )

(defclass record_ros::String_cmdResponse
  :super ros::object
  :slots (_res ))

(defmethod record_ros::String_cmdResponse
  (:init
   (&key
    ((:res __res) "")
    )
   (send-super :init)
   (setq _res (string __res))
   self)
  (:res
   (&optional __res)
   (if __res (setq _res __res)) _res)
  (:serialization-length
   ()
   (+
    ;; string _res
    4 (length _res)
    ))
  (:serialize
   (&optional strm)
   (let ((s (if strm strm
              (make-string-output-stream (send self :serialization-length)))))
     ;; string _res
       (write-long (length _res) s) (princ _res s)
     ;;
     (if (null strm) (get-output-stream-string s))))
  (:deserialize
   (buf &optional (ptr- 0))
   ;; string _res
     (let (n) (setq n (sys::peek buf ptr- :integer)) (incf ptr- 4) (setq _res (subseq buf ptr- (+ ptr- n))) (incf ptr- n))
   ;;
   self)
  )

(defclass record_ros::String_cmd
  :super ros::object
  :slots ())

(setf (get record_ros::String_cmd :md5sum-) "d4463b49bd5bb77dbd8c4356f5dc1c28")
(setf (get record_ros::String_cmd :datatype-) "record_ros/String_cmd")
(setf (get record_ros::String_cmd :request) record_ros::String_cmdRequest)
(setf (get record_ros::String_cmd :response) record_ros::String_cmdResponse)

(defmethod record_ros::String_cmdRequest
  (:response () (instance record_ros::String_cmdResponse :init)))

(setf (get record_ros::String_cmdRequest :md5sum-) "d4463b49bd5bb77dbd8c4356f5dc1c28")
(setf (get record_ros::String_cmdRequest :datatype-) "record_ros/String_cmdRequest")
(setf (get record_ros::String_cmdRequest :definition-)
      "string cmd
---
string res

")

(setf (get record_ros::String_cmdResponse :md5sum-) "d4463b49bd5bb77dbd8c4356f5dc1c28")
(setf (get record_ros::String_cmdResponse :datatype-) "record_ros/String_cmdResponse")
(setf (get record_ros::String_cmdResponse :definition-)
      "string cmd
---
string res

")



(provide :record_ros/String_cmd "d4463b49bd5bb77dbd8c4356f5dc1c28")


