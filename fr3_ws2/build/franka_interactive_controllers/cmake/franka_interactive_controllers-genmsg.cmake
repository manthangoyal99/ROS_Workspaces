# generated from genmsg/cmake/pkg-genmsg.cmake.em

message(WARNING "Invoking generate_messages() without having added any message or service file before.
You should either add add_message_files() and/or add_service_files() calls or remove the invocation of generate_messages().")
message(STATUS "franka_interactive_controllers: 0 messages, 0 services")

set(MSG_I_FLAGS "")

# Find all generators
find_package(gencpp REQUIRED)
find_package(geneus REQUIRED)
find_package(genlisp REQUIRED)
find_package(gennodejs REQUIRED)
find_package(genpy REQUIRED)

add_custom_target(franka_interactive_controllers_generate_messages ALL)

# verify that message/service dependencies have not changed since configure



#
#  langs = gencpp;geneus;genlisp;gennodejs;genpy
#

### Section generating for lang: gencpp
### Generating Messages

### Generating Services

### Generating Module File
_generate_module_cpp(franka_interactive_controllers
  ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/franka_interactive_controllers
  "${ALL_GEN_OUTPUT_FILES_cpp}"
)

add_custom_target(franka_interactive_controllers_generate_messages_cpp
  DEPENDS ${ALL_GEN_OUTPUT_FILES_cpp}
)
add_dependencies(franka_interactive_controllers_generate_messages franka_interactive_controllers_generate_messages_cpp)

# add dependencies to all check dependencies targets

# target for backward compatibility
add_custom_target(franka_interactive_controllers_gencpp)
add_dependencies(franka_interactive_controllers_gencpp franka_interactive_controllers_generate_messages_cpp)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS franka_interactive_controllers_generate_messages_cpp)

### Section generating for lang: geneus
### Generating Messages

### Generating Services

### Generating Module File
_generate_module_eus(franka_interactive_controllers
  ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/franka_interactive_controllers
  "${ALL_GEN_OUTPUT_FILES_eus}"
)

add_custom_target(franka_interactive_controllers_generate_messages_eus
  DEPENDS ${ALL_GEN_OUTPUT_FILES_eus}
)
add_dependencies(franka_interactive_controllers_generate_messages franka_interactive_controllers_generate_messages_eus)

# add dependencies to all check dependencies targets

# target for backward compatibility
add_custom_target(franka_interactive_controllers_geneus)
add_dependencies(franka_interactive_controllers_geneus franka_interactive_controllers_generate_messages_eus)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS franka_interactive_controllers_generate_messages_eus)

### Section generating for lang: genlisp
### Generating Messages

### Generating Services

### Generating Module File
_generate_module_lisp(franka_interactive_controllers
  ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/franka_interactive_controllers
  "${ALL_GEN_OUTPUT_FILES_lisp}"
)

add_custom_target(franka_interactive_controllers_generate_messages_lisp
  DEPENDS ${ALL_GEN_OUTPUT_FILES_lisp}
)
add_dependencies(franka_interactive_controllers_generate_messages franka_interactive_controllers_generate_messages_lisp)

# add dependencies to all check dependencies targets

# target for backward compatibility
add_custom_target(franka_interactive_controllers_genlisp)
add_dependencies(franka_interactive_controllers_genlisp franka_interactive_controllers_generate_messages_lisp)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS franka_interactive_controllers_generate_messages_lisp)

### Section generating for lang: gennodejs
### Generating Messages

### Generating Services

### Generating Module File
_generate_module_nodejs(franka_interactive_controllers
  ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/franka_interactive_controllers
  "${ALL_GEN_OUTPUT_FILES_nodejs}"
)

add_custom_target(franka_interactive_controllers_generate_messages_nodejs
  DEPENDS ${ALL_GEN_OUTPUT_FILES_nodejs}
)
add_dependencies(franka_interactive_controllers_generate_messages franka_interactive_controllers_generate_messages_nodejs)

# add dependencies to all check dependencies targets

# target for backward compatibility
add_custom_target(franka_interactive_controllers_gennodejs)
add_dependencies(franka_interactive_controllers_gennodejs franka_interactive_controllers_generate_messages_nodejs)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS franka_interactive_controllers_generate_messages_nodejs)

### Section generating for lang: genpy
### Generating Messages

### Generating Services

### Generating Module File
_generate_module_py(franka_interactive_controllers
  ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/franka_interactive_controllers
  "${ALL_GEN_OUTPUT_FILES_py}"
)

add_custom_target(franka_interactive_controllers_generate_messages_py
  DEPENDS ${ALL_GEN_OUTPUT_FILES_py}
)
add_dependencies(franka_interactive_controllers_generate_messages franka_interactive_controllers_generate_messages_py)

# add dependencies to all check dependencies targets

# target for backward compatibility
add_custom_target(franka_interactive_controllers_genpy)
add_dependencies(franka_interactive_controllers_genpy franka_interactive_controllers_generate_messages_py)

# register target for catkin_package(EXPORTED_TARGETS)
list(APPEND ${PROJECT_NAME}_EXPORTED_TARGETS franka_interactive_controllers_generate_messages_py)



if(gencpp_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/franka_interactive_controllers)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${gencpp_INSTALL_DIR}/franka_interactive_controllers
    DESTINATION ${gencpp_INSTALL_DIR}
  )
endif()

if(geneus_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/franka_interactive_controllers)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${geneus_INSTALL_DIR}/franka_interactive_controllers
    DESTINATION ${geneus_INSTALL_DIR}
  )
endif()

if(genlisp_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/franka_interactive_controllers)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${genlisp_INSTALL_DIR}/franka_interactive_controllers
    DESTINATION ${genlisp_INSTALL_DIR}
  )
endif()

if(gennodejs_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/franka_interactive_controllers)
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${gennodejs_INSTALL_DIR}/franka_interactive_controllers
    DESTINATION ${gennodejs_INSTALL_DIR}
  )
endif()

if(genpy_INSTALL_DIR AND EXISTS ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/franka_interactive_controllers)
  install(CODE "execute_process(COMMAND \"/usr/bin/python3\" -m compileall \"${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/franka_interactive_controllers\")")
  # install generated code
  install(
    DIRECTORY ${CATKIN_DEVEL_PREFIX}/${genpy_INSTALL_DIR}/franka_interactive_controllers
    DESTINATION ${genpy_INSTALL_DIR}
  )
endif()
