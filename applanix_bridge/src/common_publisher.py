# ROS
import roslib; roslib.load_manifest('applanix_bridge')
import rospy
import tf
import PyKDL

# Applanix node internal messages & modules
from applanix_msgs.msg import NavigationSolution, GNSSStatus, IMUData
from gps_utm import LLtoUTM

# ROS standard messages
from sensor_msgs.msg import Imu, NavSatFix, NavSatStatus
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Quaternion, Point

# Other
from math import radians as RAD

# FIXED COVARIANCES
# TODO: Work these out...
IMU_ORIENT_COVAR = [1e-3, 0, 0,
                    0, 1e-3, 0,
                    0, 0, 1e-3]

IMU_VEL_COVAR = [1e-3, 0, 0,
                 0, 1e-3, 0,
                 0, 0, 1e-3]

IMU_ACCEL_COVAR = [1e-3, 0, 0,
                   0, 1e-3, 0,
                   0, 0, 1e-3]

NAVSAT_COVAR = [1, 0, 0,
                0, 1, 0,
                0, 0, 1]

POSE_COVAR = [1, 0, 0, 0, 0, 0,
              0, 1, 0, 0, 0, 0,
              0, 0, 1, 0, 0, 0,
              0, 0, 0, 0.1, 0, 0,
              0, 0, 0, 0, 0.1, 0,
              0, 0, 0, 0, 0, 0.1]

TWIST_COVAR = [1, 0, 0, 0, 0, 0,
               0, 1, 0, 0, 0, 0,
               0, 0, 1, 0, 0, 0,
               0, 0, 0, 0.1, 0, 0,
               0, 0, 0, 0, 0.1, 0,
               0, 0, 0, 0, 0, 0.1]

class ApplanixPublisher(object):

    def __init__(self):
        rospy.init_node('applanix_publisher')
        # Parameters
        self.publish_tf = rospy.get_param('~publish_tf', False)
        self.odom_frame = rospy.get_param('~odom_frame', 'odom')
        self.base_frame = rospy.get_param('~base_frame', 'base_footprint')

        # Topic publishers
        self.pub_imu = rospy.Publisher('imu_data', Imu)
        self.pub_odom = rospy.Publisher('gps_odom', Odometry)
        self.pub_navsatfix = rospy.Publisher('gps_fix', NavSatFix)
        self.pub_navsatstatus = rospy.Publisher('gps_status', NavSatStatus)
        if self.publish_tf:
            self.tf_broadcast = tf.TransfromBroadcaster()

        # Init nav status
        self.nav_status = NavSatStatus()    # We need this for the NavSatFix broadcaster
        self.nav_status.status = NavSatStatus.STATUS_NO_FIX
        self.nav_status.service = NavSatStatus.SERVICE_GPS

        self.init = False       # If we've been initialized
        self.origin = Point()   # Where we've started
        
        # Subscribed topics
        rospy.Subscriber('nav', NavigationSolution, self.navigation_handler)
        rospy.Subscriber('status/gnss/primary', GNSSStatus, self.status_handler)
       
    def navigation_handler(self, data):
        """ Rebroadcasts navigation data in the following formats:
        1) /odom => /base footprint transform (if enabled, as per REP 105)
        2) Odometry message, with parent/child IDs as in #1
        3) NavSatFix message, for systems which are knowledgeable about GPS stuff
        4) IMU messages
        """
        # If we don't have a fix, don't publish anything...
        if self.nav_status.status == NavSatStatus.STATUS_NO_FIX:
            return
        
        orient = PyKDL.Rotation.RPY(RAD(data.roll), RAD(data.pitch), RAD(data.yaw)).GetQuaternion()

        # UTM conversion
        (zone, easting, northing) = LLtoUTM(23, data.latitude, data.longitude)
        # Initialize starting point if we haven't yet
        # TODO: Do we want to follow UTexas' lead and reinit to a nonzero point within the same UTM grid?
        if not self.init:
            self.origin.x = easting
            self.origin.y = northing
            self.init = True

        #
        # Odometry 
        # TODO: Work out these covariances properly from DOP
        #
        odom = Odometry()
        odom.header.stamp = rospy.Time.now()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x = easting - self.origin.x
        odom.pose.pose.position.y = northing - self.origin.y
        odom.pose.pose.position.z = data.altitude
        odom.pose.pose.orientation = Quaternion(*orient)
        odom.pose.covariance = POSE_COVAR
        # Twist is relative to /vehicle frame
        odom.twist.twist.linear.x = speed
        odom.twist.twist.linear.y = 0
        odom.twist.twist.linear.z = -data.down_vel
        odom.twist.twist.angular.x = RAD(data.ang_rate_long)
        odom.twist.twist.angular.y = RAD(-data.ang_rate_trans)
        odom.twist.twist.angular.z = RAD(-data.ang_rate_down)
        odom.twist.covariance = TWIST_COVAR

        self.pub_odom(odom)

        #
        # Odometry transform (if required)
        #
        if self.publish_tf:
            self.tf_broadcast.sendTransform(
                (odom.pose.pose.position.x, odom.pose.pose.position.y,
                 odom.pose.pose.position.z), Quaternion(*orient),
                 odom.header.stamp,odom.child_frame_id, odom.frame_id)

        # 
        # NavSatFix
        # TODO: Work out these covariances properly from DOP
        #
        navsat = NavSatFix()
        navsat.header.stamp = rospy.Time.now()
        navsat.header.frame_id = self.odom_frame
        navsat.status = self.nav_status

        navsat.latitude = data.latitude
        navsat.longitude = data.longitude
        navsat.altitude = data.altitude

        navsat.position_covariance = NAVSAT_COVAR
        navsat.position_covariance_type = NavSatFix.COVARIANCE_TYPE_UNKNOWN
        
        self.pub_navsatfix(navsat)
        
        #
        # IMU
        # TODO: Work out these covariances properly
        #
        imu = Imu()
        imu.header.stamp == rospy.Time.now()
        imu.header.frame_id = self.base_frame
      
        # Orientation
        imu.orientation = Quaternion(*orient)
        imu.orientation_covariance = IMU_ORIENT_COVAR
 
        # Angular rates
        imu.angular_velocity.x = RAD(data.ang_rate_long)
        imu.angular_velocity.y = RAD(-data.ang_rate_trans)
        imu.angular_velocity.y = RAD(-data.ang_rate_down)
        imu.angular_velocity_covariance = IMU_VEL_COVAR

        # Linear acceleration
        imu.linear_acceleration.x = data.long_accel
        imu.linear_acceleration.y = data.trans_accel
        imu.linear_acceleration.z = data.down_accel
        imu.linear_acceleration_covariance = IMU_ACCEL_COVAR

        self.pub_imu.publish(imu)
        
         
        pass

    def status_handler(self, data):
        """ Rebroadcasts GNSS status as a standard NavSatStatus message """
        # In the below, not sure about mapping the "DGPS" status to SBAS instead of GBAS
        solution_map = {
            GNSSStatus.SOLUTION_UNKNOWN: NavSatStatus.STATUS_NO_FIX,
            GNSSStatus.SOLUTION_NO_DATA: NavSatStatus.STATUS_NO_FIX,
            GNSSStatus.SOLUTION_HORIZONAL_CA: NavSatStatus.STATUS_FIX,
            GNSSStatus.SOLUTION_3D_CA: NavSatStatus.STATUS_FIX,
            GNSSStatus.SOLUTION_HORIZONTAL_DGPS: NavSatStatus.STATUS_SBAS_FIX,
            GNSSStatus.SOLUTION_3D_DGPS: NavSatStatus.STATUS_SBAS_FIX,
            GNSSStatus.SOLUTION_FLOAT_RTK: NavSatStatus.STATUS_GBAS_FIX,
            GNSSStatus.SOLUTION_WIDE_LANE_RTK: NavSatStatus.STATUS_GBAS_FIX,
            GNSSStatus.SOLUTION_NARROW_LANE_RTK: NavSatStatus.STATUS_GBAS_FIX,
            GNSSStatus.SOLUTION_P_CODE: NavSatStatus.STATUS_FIX,
            GNSSStatus.SOLUTION_OMNISTAR_HP: NavSatStatus.STATUS_SBAS_FIX,
            GNSSStatus.SOLUTION_OMNISTAR_XP: NavSatStatus.STATUS_SBAS_FIX,
            GNSSStatus.SOLUTION_OMNISTAR_VBS: NavSatStatus.STATUS_SBAS_FIX,
            }
        self.nav_status.status = solution_map.get(data.solution_status,NavSatStatus.STATUS_NO_FIX)

        # Assume GPS - this isn't exposed
        self.nav_status.service = NavSatStatus.SERVICE_GPS
            
        self.pub_navsatstatus.publish(self.nav_status)
        
if __name__ == '__main__':
    node = ApplanixPublisher()
