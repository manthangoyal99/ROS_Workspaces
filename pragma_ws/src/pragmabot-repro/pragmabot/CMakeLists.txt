cmake_minimum_required(VERSION 3.9)
project(pragmabot)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  sensor_msgs
  geometry_msgs
  message_filters
  cv_bridge
  image_transport
  topic_tools
  tf
)

catkin_python_setup()

catkin_package(
  CATKIN_DEPENDS
    rospy
    std_msgs
    sensor_msgs
    geometry_msgs
    message_filters
    cv_bridge
    image_transport
    topic_tools
    tf
)

catkin_install_python(
  PROGRAMS
    nodes/pragmabot_node.py
    nodes/memory_manager_node.py
    nodes/image_republisher_node.py
    nodes/realsense_zmq_bridge.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
  FILES_MATCHING PATTERN "*.launch"
)

install(DIRECTORY config/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/config
  FILES_MATCHING PATTERN "*.yaml"
)
