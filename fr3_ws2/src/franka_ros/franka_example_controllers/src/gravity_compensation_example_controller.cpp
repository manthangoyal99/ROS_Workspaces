#include <franka_example_controllers/gravity_compensation_example_controller.h>
#include <pluginlib/class_list_macros.h>

namespace franka_example_controllers {

bool GravityCompensationExampleController::init(hardware_interface::RobotHW* robot_hw,
                                                ros::NodeHandle& node_handle) {
  // 1. Get the Effort Interface (to send Torques)
  auto* effort_joint_interface = robot_hw->get<hardware_interface::EffortJointInterface>();
  if (effort_joint_interface == nullptr) {
    ROS_ERROR("GravityComp: Could not get EffortJointInterface");
    return false;
  }

  // 2. Get the Joint Names (from parameter server)
  std::vector<std::string> joint_names;
  if (!node_handle.getParam("joint_names", joint_names) || joint_names.size() != 7) {
    ROS_ERROR("GravityComp: Invalid or no joint_names parameters provided");
    return false;
  }

  // 3. Create Handles for all 7 joints
  joint_handles_.resize(7);
  for (size_t i = 0; i < 7; ++i) {
    try {
      joint_handles_[i] = effort_joint_interface->getHandle(joint_names[i]);
    } catch (const hardware_interface::HardwareInterfaceException& ex) {
      ROS_ERROR_STREAM("GravityComp: Exception getting joint handle: " << ex.what());
      return false;
    }
  }

  return true;
}

void GravityCompensationExampleController::update(const ros::Time& /*time*/,
                                                  const ros::Duration& /*period*/) {
  // THE MAGIC: Send 0.0 torque.
  // The robot's internal controller adds the gravity term automatically.
  for (auto& joint_handle : joint_handles_) {
    joint_handle.setCommand(0.0);
  }
}

}  // namespace franka_example_controllers

// Register the controller as a plugin
PLUGINLIB_EXPORT_CLASS(franka_example_controllers::GravityCompensationExampleController,
                       controller_interface::ControllerBase)