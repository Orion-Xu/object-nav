FROM ros:noetic-ros-base-focal

SHELL ["/bin/bash", "-c"]
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential cmake libpcl-dev python3-opencv \
    ros-noetic-cv-bridge ros-noetic-image-transport ros-noetic-pcl-ros \
    ros-noetic-camera-info-manager ros-noetic-dynamic-reconfigure \
    && rm -rf /var/lib/apt/lists/*
COPY vendor/camport_ros/src /camera_ws/src
ENV LD_LIBRARY_PATH=/camera_ws/src/percipio_camera/camport4/lib/linux/lib_x64
RUN source /opt/ros/noetic/setup.bash && catkin_make -C /camera_ws -DCMAKE_BUILD_TYPE=Release
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["bash", "-lc", "source /camera_ws/devel/setup.bash && rosrun percipio_camera list_devices"]
