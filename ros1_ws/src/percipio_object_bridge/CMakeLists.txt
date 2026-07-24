cmake_minimum_required(VERSION 3.0.2)
project(percipio_object_bridge)

find_package(catkin REQUIRED COMPONENTS cv_bridge message_filters rospy sensor_msgs)
catkin_package()

catkin_install_python(PROGRAMS scripts/rgbd_tcp_bridge.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
