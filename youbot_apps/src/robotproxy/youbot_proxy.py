
'''
@author: Rick Candell
@contact: rick.candell@nist.gov
@organization: NIST
@license: public domain
'''

import sys
import copy
import rospy
import moveit_commander
from base_proxy import BaseProxy, ProxyCommand
#from geometry_msgs.msg import PoseStamped
#from tf.transformations import quaternion_from_euler
from brics_actuator.msg import JointPositions, JointValue
from sensor_msgs.msg import JointState


class YouboProxy(BaseProxy):
    
    # class attributes
    arm_joint_names = ['arm_joint_1', 'arm_joint_2', 'arm_joint_3', 'arm_joint_4', 'arm_joint_5']
    gripper_joint_names = ['gripper_finger_joint_l', 'gripper_finger_joint_r']
    #TODO delete: end_effector_link = "gripper_pointer_link"    
    
    def __init__(self, node_name):
        rospy.logdebug("YoubotProxy __init__")
        super(YoubotProxy,self).__init__()
        self.init_done = False  # indicates that the object was initialized 
        
        # init ros node
        rospy.init_node(node_name, anonymous=True)
        rospy.loginfo("ROS node initialized: " + rospy.get_name())
        rospy.loginfo("node namespace is : " + rospy.get_namespace())
        rospy.loginfo("node uri is : " + rospy.get_node_uri())
        
        # init object attributes
        self.arm_num = rospy.get_param("~arm_num")

        # init joint_states subscriber
        self._joint_states_arm = None
        self._joint_states_gripper = None        
        # todo: create thread event object for joint_states variable
        self._joint_states_topic = rospy.get_param("~joint_states_topic")
        self._joint_states_sub = rospy.Subscriber(self._joint_states_topic, JointState, self.joint_states_cb)  
        
    def joint_states_cb(self, data):
        try:
            # todo: wait for lock release
            self._joint_states = data
        except:
            pass
        finally:
            # add threading event to lock the variable until operating completes
            #   use finaly to ensure lock is released
            pass

        # Gripper distance tolerance: 1 mm 
        self.gripper_distance_tol = rospy.get_param("~gripper_distance_tol", 0.001) 
        # Joint distance tolerance: 1/10 radian tolerance (1.2 degrees)
        self.joint_distance_tol = rospy.get_param("~joint_distance_tol",0.02)
        
        # init moveit
        try:
            moveit_commander.roscpp_initialize(sys.argv)
            self.arm_group = moveit_commander.MoveGroupCommander("manipulator")
            self.arm_group.set_planning_time(8)
            self.arm_group.set_pose_reference_frame("base_link")
            rospy.loginfo("planning group created for manipulator")
        except:
            pass

        # init arm publisher
        self._arm_pub = rospy.Publisher("arm_" + str(self.arm_num) + "/arm_controller/position_command", JointPositions)
        rospy.loginfo("Created arm joint position publisher ")
        
        # init gripper action client
        self._gripper_pub = rospy.Publisher("arm_" + str(self.arm_num) + "/gripper_controller/position_command", JointPositions)
        rospy.loginfo("Created gripper joint position publisher ")
        
        # set init done flag
        self.init_done = True
                
                
    def plan_arm(self, pose): 
        '''
        @param pose: a PoseStamped object
        @precondition: initialize_node must be called first 
        @return: boolean
        @note: sets the intended goal in self
        '''
        raise NotImplementedError 

    def make_brics_msg_arm(positions):
        # create joint positions message
        jp = JointPositions()
        for ii in range(5):
            jv = JointValue()
            jv.joint_uri = 'arm_joint_' + str(ii+1)
            jv.unit='rad' 
            jv.value = positions[ii]
            jp.positions.append(copy.deepcopy(jv))
        return jp

    def move_arm(self):
        # Sends the goal to the action server.
        self._ac_arm.send_goal(self._arm_goal, feedback_cb=self.move_arm_feedback_cb)
    
        # Waits for the server to finish performing the action.
        self._ac_arm.wait_for_result()  
    
        # get the result code
        return self._ac_arm.get_result()    
    
    def make_brics_msg_gripper(opening_m):

        # Turn a desired gripper opening into a brics-friendly message    
        left = opening_m/2.
        right = opening_m/2.
        # create joint positions message
        jp = JointPositions()

        # create joint values message for both left and right fingers
        jvl = JointValue()
        jvr = JointValue()

        # Fill in the gripper positions desired
        # This is open position (max opening 0.0115 m)
        jvl.joint_uri = 'gripper_finger_joint_l'
        jvl.unit = 'm'
        jvl.value = left
        jvr.joint_uri = 'gripper_finger_joint_r'
        jvr.unit = 'm'
        jvr.value = right

        # Append those onto JointPositions
        jp.positions.append(copy.deepcopy(jvl))
        jp.positions.append(copy.deepcopy(jvr))

        return jp    

    def move_gripper(self, opening_m): 
        # ALERT! Make sure width of opening is no larger than 0.023 m (23 mm)
        if opening_m > 0.23:
            raise Exception("gripper opening is too large: " + str(opening_m))
        jp = YoubotProxy.make_brics_msg_gripper(opening_m)
        rospy.logdebug("make_brics_msg_gripper position message")
        rospy.logdebug(jp)

        # Initialize the timer for gripper publisher
        r = rospy.Rate(10) # 10hz
        while not rospy.is_shutdown():
            rospy.loginfo("moving gripper")
            self._gripper_pub.publish(jp)
            if BaseProxy.measure_euclidean_distance([opening_m/2 opening_m/2], ) < self.gripper_distance_tol:
                break 
            r.sleep()   

    def control_loop(self):
        if self.commands is None:
            raise Exception('Command list is empty.  Was the control plan loaded?')
        
        # loop through the command list
        for cmd in self.commands:

            # wait for proxy to be in active state
            self.wait_for_state(self._proxy_state_running)
            
            # process commands
            cmd_spec_str = None
            spec = None
            t = cmd[ProxyCommand.key_command_type]
            if not (t == "noop"):
                cmd_spec_str = cmd[ProxyCommand.key_command_spec]
                if not isinstance(cmd_spec_str, basestring):
                    spec = float(cmd_spec_str)
                else:
                    spec = self.positions[cmd_spec_str]
                rospy.loginfo("Command type: " + t + ", spec: " + str(cmd_spec_str) + ", value: " + str(spec))
                       
            # check for any wait depends
            self.wait_for_depend(cmd)

            # execute command
            # could do this with a dictionary-based function lookup, but who cares
            if t == 'noop':
                rospy.loginfo("Command type: noop")
                self.wait_for_depend(cmd)
            elif t == 'sleep':
                rospy.loginfo("sleep command")
                v = float(spec)
                rospy.sleep(v)
            elif t == 'move_gripper':
                rospy.loginfo("gripper command")
                self.move_gripper(spec)
            elif t == 'move_arm':
                rospy.loginfo("move_arm command")
                rospy.logdebug(spec)                
                goal = FollowJointTrajectoryGoal()
                goal.trajectory.joint_names = self.arm_joint_names
                jtp = JointTrajectoryPoint()
                jtp.time_from_start = rospy.Duration(0.5)  # fudge factor for gazebo controller
                jtp.positions = spec
                jtp.velocities = [0]*len(spec)
                goal.trajectory.points.append(jtp)
                self._arm_goal = copy.deepcopy(goal)
                self.move_arm()
            elif t == 'plan_exec_arm':
                rospy.loginfo("plan and execute command not implemented")
                raise NotImplementedError()
            else:
                raise Exception("Invalid command type: " + str(cmd.type))

            # check for any set dependencies action
            self.set_depend(cmd)

            # check for any clear dependencies action
            self.clear_depend(cmd)




