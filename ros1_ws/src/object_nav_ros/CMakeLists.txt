cmake_minimum_required(VERSION 3.0.2)
project(object_nav_ros)

find_package(catkin REQUIRED COMPONENTS actionlib geometry_msgs move_base_msgs rospy tf2_ros)
catkin_package()

catkin_install_python(PROGRAMS
  scripts/move_base_adapter_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
