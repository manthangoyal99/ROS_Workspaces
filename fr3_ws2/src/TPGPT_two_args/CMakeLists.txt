cmake_minimum_required(VERSION 3.0.2)
project(TPGPT_two_args)

## Compile as C++11, supported in ROS Kinetic and newer
add_compile_options(-std=c++11)

## Find catkin macros and libraries
find_package(catkin REQUIRED COMPONENTS
  rospy
  geometry_msgs
  tf2_ros
  std_msgs
)

## System dependencies are found with CMake's conventions
# find_package(Boost REQUIRED COMPONENTS system)

################################################
## Declare ROS messages, services and actions ##
################################################

## (If you aren't defining custom .msg files, you can leave this section commented out)

################################################
##               Build                        ##
################################################

catkin_package(
#  INCLUDE_DIRS include
#  LIBRARIES reshelving_policy_transport
#  CATKIN_DEPENDS rospy geometry_msgs tf2_ros std_msgs
#  DEPENDS system_lib
)

## (If you have C++ nodes, add them here. Since you only have Python scripts for now, we skip add_executable)

################################################
##               Install                      ##
################################################

## Mark executable scripts (Python etc.) for installation
## in contrast to setup.py, you can choose the destination
catkin_install_python(PROGRAMS
  scripts/run_new_traj_vel.py
  scripts/run_new_traj_vel2.py
  scripts/demo_recorder.py
  scripts/demo_traj_validator.py
  scripts/run_new_traj.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
