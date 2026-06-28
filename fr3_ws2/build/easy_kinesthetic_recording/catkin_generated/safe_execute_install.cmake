execute_process(COMMAND "/home/ravi/fr3_ws2/build/easy_kinesthetic_recording/catkin_generated/python_distutils_install.sh" RESULT_VARIABLE res)

if(NOT res EQUAL 0)
  message(FATAL_ERROR "execute_process(/home/ravi/fr3_ws2/build/easy_kinesthetic_recording/catkin_generated/python_distutils_install.sh) returned error code ")
endif()
