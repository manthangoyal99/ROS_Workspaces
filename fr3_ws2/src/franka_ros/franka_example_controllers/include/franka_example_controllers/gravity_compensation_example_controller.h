#pragma once

#include <memory>
#include <string>
#include <vector>

#include <controller_interface/multi_interface_controller.h>
#include <hardware_interface/joint_command_interface.h>
#include <hardware_interface/robot_hw.h>
#include <ros/node_handle.h>
#include <ros/time.h>

namespace franka_example_controllers {

class GravityCompensationExampleController : public controller_interface::MultiInterfaceController<
                                               hardware_interface::EffortJointInterface> {
 public:
  bool init(hardware_interface::RobotHW* robot_hw, ros::NodeHandle& node_handle) override;
  void update(const ros::Time&, const ros::Duration& period) override;

 private:
  std::vector<hardware_interface::JointHandle> joint_handles_;
};

}  // namespace franka_example_controllers
