# generated from genmsg/cmake/pkg-genmsg.cmake.em

message(STATUS "record_ros: 0 messages, 1 services")

set(MSG_I_FLAGS "-Istd_msgs:/opt/ros/noetic/share/std_msgs/cmake/../msg")

# Find all generators
find_package(gencpp REQUIRED)
find_package(geneus REQUIRED)
find_package(genlisp REQUIRED)
find_package(gennodejs REQUIRED)
find_package(genpy REQUIRED)

add_custom_target(record_ros_generate_messages ALL)

# verify that message/service dependencies have not changed since configure



get_filename_component(_filename "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" NAME_WE)
add_custom_target(_record_ros_generate_messages_check_deps_${_filename}
  COMMAND ${CATKIN_ENV} ${PYTHON_EXECUTABLE} ${GENMSG_CHECK_DEPS_SCRIPT} "record_ros" "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" ""
)

#
#  langs = gencpp;geneus;genlisp;gennodejs;genpy
#

### Section generating for lang: gencpp
### Generating Messages

### Generating Services
_generate_srv_cpp(record_ros
  "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv"
  "${MSG_I_FLAGS}"
  ""
  ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/record_ros
)

### Generating Module File
_generate_module_cpp(record_ros
  ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/record_ros
  "${ALL_GEN_OUTPUT_FILES_cpp}"
)

add_custom_target(record_ros_generate_messages_cpp
  DEPENDS ${ALL_GEN_OUTPUT_FILES_cpp}
)
add_dependencies(record_ros_generate_messages record_ros_generate_messages_cpp)

# add dependencies to all check dependencies targets
get_filename_component(_filename "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" NAME_WE)
add_dependencies(record_ros_generate_messages_cpp _record_ros_generate_messages_check_deps_${_filename})

# target for backward compatibility
add_custom_target(record_ros_gencpp)
add_dependencies(record_ros_gencpp record_ros_generate_messages_cpp)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS record_ros_generate_messages_cpp)

### Section generating for lang: geneus
### Generating Messages

### Generating Services
_generate_srv_eus(record_ros
  "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv"
  "${MSG_I_FLAGS}"
  ""
  ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/record_ros
)

### Generating Module File
_generate_module_eus(record_ros
  ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/record_ros
  "${ALL_GEN_OUTPUT_FILES_eus}"
)

add_custom_target(record_ros_generate_messages_eus
  DEPENDS ${ALL_GEN_OUTPUT_FILES_eus}
)
add_dependencies(record_ros_generate_messages record_ros_generate_messages_eus)

# add dependencies to all check dependencies targets
get_filename_component(_filename "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" NAME_WE)
add_dependencies(record_ros_generate_messages_eus _record_ros_generate_messages_check_deps_${_filename})

# target for backward compatibility
add_custom_target(record_ros_geneus)
add_dependencies(record_ros_geneus record_ros_generate_messages_eus)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS record_ros_generate_messages_eus)

### Section generating for lang: genlisp
### Generating Messages

### Generating Services
_generate_srv_lisp(record_ros
  "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv"
  "${MSG_I_FLAGS}"
  ""
  ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/record_ros
)

### Generating Module File
_generate_module_lisp(record_ros
  ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/record_ros
  "${ALL_GEN_OUTPUT_FILES_lisp}"
)

add_custom_target(record_ros_generate_messages_lisp
  DEPENDS ${ALL_GEN_OUTPUT_FILES_lisp}
)
add_dependencies(record_ros_generate_messages record_ros_generate_messages_lisp)

# add dependencies to all check dependencies targets
get_filename_component(_filename "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" NAME_WE)
add_dependencies(record_ros_generate_messages_lisp _record_ros_generate_messages_check_deps_${_filename})

# target for backward compatibility
add_custom_target(record_ros_genlisp)
add_dependencies(record_ros_genlisp record_ros_generate_messages_lisp)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS record_ros_generate_messages_lisp)

### Section generating for lang: gennodejs
### Generating Messages

### Generating Services
_generate_srv_nodejs(record_ros
  "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv"
  "${MSG_I_FLAGS}"
  ""
  ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/record_ros
)

### Generating Module File
_generate_module_nodejs(record_ros
  ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/record_ros
  "${ALL_GEN_OUTPUT_FILES_nodejs}"
)

add_custom_target(record_ros_generate_messages_nodejs
  DEPENDS ${ALL_GEN_OUTPUT_FILES_nodejs}
)
add_dependencies(record_ros_generate_messages record_ros_generate_messages_nodejs)

# add dependencies to all check dependencies targets
get_filename_component(_filename "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" NAME_WE)
add_dependencies(record_ros_generate_messages_nodejs _record_ros_generate_messages_check_deps_${_filename})

# target for backward compatibility
add_custom_target(record_ros_gennodejs)
add_dependencies(record_ros_gennodejs record_ros_generate_messages_nodejs)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS record_ros_generate_messages_nodejs)

### Section generating for lang: genpy
### Generating Messages

### Generating Services
_generate_srv_py(record_ros
  "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv"
  "${MSG_I_FLAGS}"
  ""
  ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/record_ros
)

### Generating Module File
_generate_module_py(record_ros
  ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/record_ros
  "${ALL_GEN_OUTPUT_FILES_py}"
)

add_custom_target(record_ros_generate_messages_py
  DEPENDS ${ALL_GEN_OUTPUT_FILES_py}
)
add_dependencies(record_ros_generate_messages record_ros_generate_messages_py)

# add dependencies to all check dependencies targets
get_filename_component(_filename "/home/ravi/fr3_ws2/src/record_ros/srv/String_cmd.srv" NAME_WE)
add_dependencies(record_ros_generate_messages_py _record_ros_generate_messages_check_deps_${_filename})

# target for backward compatibility
add_custom_target(record_ros_genpy)
add_dependencies(record_ros_genpy record_ros_generate_messages_py)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS record_ros_generate_messages_py)



if(gencpp_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/record_ros)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/record_ros
    DESTINATION ${gencpp_INSTALL_DIR}
  )
endif()
if(TARGET std_msgs_generate_messages_cpp)
  add_dependencies(record_ros_generate_messages_cpp std_msgs_generate_messages_cpp)
endif()

if(geneus_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/record_ros)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/record_ros
    DESTINATION ${geneus_INSTALL_DIR}
  )
endif()
if(TARGET std_msgs_generate_messages_eus)
  add_dependencies(record_ros_generate_messages_eus std_msgs_generate_messages_eus)
endif()

if(genlisp_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/record_ros)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/record_ros
    DESTINATION ${genlisp_INSTALL_DIR}
  )
endif()
if(TARGET std_msgs_generate_messages_lisp)
  add_dependencies(record_ros_generate_messages_lisp std_msgs_generate_messages_lisp)
endif()

if(gennodejs_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/record_ros)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/record_ros
    DESTINATION ${gennodejs_INSTALL_DIR}
  )
endif()
if(TARGET std_msgs_generate_messages_nodejs)
  add_dependencies(record_ros_generate_messages_nodejs std_msgs_generate_messages_nodejs)
endif()

if(genpy_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/record_ros)
  install(CODE "execute_process(COMMAND \"/usr/bin/python3\" -m compileall \"${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/record_ros\")")
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/record_ros
    DESTINATION ${genpy_INSTALL_DIR}
  )
endif()
if(TARGET std_msgs_generate_messages_py)
  add_dependencies(record_ros_generate_messages_py std_msgs_generate_messages_py)
endif()
