#!/usr/bin/env python3

import math
import numpy as np
import random as random
import tkinter as tk
import rospy
from nav_msgs.msg import Odometry
from fiducial_msgs.msg import FiducialTransformArray
import fastSlam1 as fs
from fastSlam1 import Particle, ParticleSet

usingVelocities = False

class FastSlamNode:

    def __init__(self):

        self.Nmarkers = 43
        self.Nparticles = 100
        self.timer_freq = 1

        self.detected_aruco_markers = []
        self.pose = (0, 0, 0)

        self.particleSet = ParticleSet(self.Nparticles)
        for _ in range(self.Nparticles):
            #Make them random
            self.particleSet.add( Particle(self.Nmarkers, 5*np.array([random.random(),random.random(),0]).astype(float)))
        
        self.animate = Animater()

        # Initialize the ROS node
        rospy.init_node('slam_node')
        rospy.loginfo_once('Slam node has started')

        # Initialize the publishers and subscribers
        self.initialize_subscribers()
        
        # Initialize the timer with the corresponding interruption to work at a constant rate
        self.initialize_timer()

    def initialize_subscribers(self):
        """
        Initialize the subscribers to the topics.
        """

        # Subscribe to pose and aruco topics
        self.sub_pose = rospy.Subscriber('/pose', Odometry, self.callback_pose_topic)
        self.sub_aruco = rospy.Subscriber('/fiducial_transforms', FiducialTransformArray, self.callback_aruco_topic)

    def initialize_timer(self):
        """
        Here we create a timer to trigger the callback function at a fixed rate.
        """
        self.timer = rospy.Timer(rospy.Duration(1/self.timer_freq), self.timer_callback)
        self.h_timerActivate = True

    def timer_callback(self, timer):
        """Here you should invoke methods to perform the logic computations of your algorithm.
        Note, the timer object is not used here, but it is passed as an argument to the callback by default.
        This callback is called at a fixed rate as defined in the initialization of the timer.
        """

        # Do something here at a fixed rate
        self.animate.update_display(self.particleSet, self.detected_aruco_markers)
    
    def callback_pose_topic(self, msg):
        """
        Callback function for the subscriber of the topic '/aruco_topic'.
        """
        if usingVelocities:
            try:
                delta_t = msg.header.stamp.secs + msg.header.stamp.nsecs/1000000000.0 - self.pose_ts
            except:
                delta_t = 0.1
            self.pose_ts = msg.header.stamp.secs + msg.header.stamp.nsecs/1000000000.0
            twist = msg.twist.twist
            twist_covariance = msg.twist.covariance
            u = np.array([twist.linear.x, twist.angular.z])
            u_vars = np.array([twist_covariance[0], twist_covariance[5], twist_covariance[35]])
            for k in range(self.Nparticles):
                fs.predict(u, self.particleSet, delta_t, k, u_vars, usingVelocities)
            rospy.loginfo('Prediction step with linear velocity %f and angular velocity %f', u[0], u[1])
        else:
            x = msg.pose.pose.position.x
            y = msg.pose.pose.position.y
            yaw = quaternion_to_yaw(msg.pose.pose.orientation)
            covariances = np.array([msg.pose.covariance[0], msg.pose.covariance[0], msg.pose.covariance[0]])
            u = np.array([x - self.pose[0], y - self.pose[1], yaw - self.pose[2]])
            for k in range(self.Nparticles):
                fs.predict(u, self.particleSet, None, k, covariances, usingVelocities)
            self.pose = (x, y, yaw)
            rospy.loginfo('Prediction step with linear velocity %f and angular velocity %f', u[0], u[1])

    
    def callback_aruco_topic(self, msg):
        """
        Callback function for the subscriber of the topic '/aruco_topic'.
        """
        for marker in msg.transforms:
            id = marker.fiducial_id
            if id not in self.detected_aruco_markers:
                self.detected_aruco_markers.append(id)
                rospy.loginfo('Marker %s detected for the first time giving a total of %d unique markers',
                              id, len(self.detected_aruco_markers))
            posCameraFrame = np.array([marker.transform.translation.x, marker.transform.translation.y,
                                       marker.transform.translation.z])
            rospy.loginfo('Received detection of marker %s (number: %d) at relative position (%f, %f, %f)',
                           id, self.detected_aruco_markers.index(id), 
                           posCameraFrame[0], posCameraFrame[1], posCameraFrame[2])
            if usingVelocities:
                self.particleSet = fs.FastSLAM(posCameraFrame, self.detected_aruco_markers.index(id),
                                            np.array([0,0]), self.particleSet, None, usingVelocities)
            else:
                self.particleSet = fs.FastSLAM(posCameraFrame, self.detected_aruco_markers.index(id),
                                            np.array([0,0,0]), self.particleSet, None, usingVelocities)

            

def quaternion_to_yaw(quaternion):
    # Extract the yaw angle from the quaternion
    qw = quaternion.w
    qx = quaternion.x
    qy = quaternion.y
    qz = quaternion.z
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return yaw

class Animater:
    def __init__(self):

        self.path=[]
        self.beacons={}
        # Initialize some necessary variables here
        self.drawing_scale = 64
        self.drawing_start = (100, 700)
        #Some GUI to see if points are being updated
        self.root = tk.Tk()
        self.canvas = tk.Canvas(self.root, width=1400, height=800)
        self.canvas.pack()

    def start_display(self):
        self.root.mainloop()

    def update_display(self, particleSet : ParticleSet, beacons: list):
        robot_pos = estimate_robot_pos(particleSet, 1) #percentage of particles to use for estimation
        if(len(self.path)):
            if np.linalg.norm(self.path[-1] - robot_pos)*self.drawing_scale > 1:
                self.path.append(robot_pos)

        else:
            self.path.append(robot_pos)
        beacons_pos = estimate_beacons_pos(particleSet, beacons)
        self.draw_particles(particleSet)
        self.draw_path()
        self.draw_beacons(beacons_pos)

    def draw_particles(self, particleSet : ParticleSet):
        self.canvas.delete('points')
        Nparticles = particleSet.M
        for i in range(Nparticles):
            x = self.drawing_start[0] + self.drawing_scale * particleSet.set[i].x[0]
            y = self.drawing_start[1] - self.drawing_scale * particleSet.set[i].x[1]
            self.canvas.create_oval(x-2, y-2, x+2, y+2, fill="blue", tags="points")

    def draw_arrow(self, x, y, angle):
        angle = -(angle+math.pi/2)
        marker_length = 15  # Length of the arrow
        
        # Calculate the coordinates of the arrow points
        x = self.drawing_start[0] + self.drawing_scale * x
        y = self.drawing_start[1] - self.drawing_scale * y
        x1 = x - 0.8*marker_length * math.cos(angle)
        y1 = y - 0.8*marker_length * math.sin(angle)
        x2 = x + 0.8*marker_length * math.cos(angle)
        y2 = y + 0.8*marker_length * math.sin(angle)
        
        # Calculate the coordinates of the arrowhead
        x3 = x + 2*marker_length * math.cos(angle + math.pi/2)
        y3 = y + 2*marker_length * math.sin(angle + math.pi/2)
        
        # Draw the arrow on the canvas
        self.canvas.create_polygon(x1, y1, x2, y2, x3, y3, fill="red")

    def draw_path(self):
        if(len(self.path) >= 2):
            x1, y1, _ = self.path[-2]
            x2, y2, _ = self.path[-1]
            x1 = self.drawing_start[0] + self.drawing_scale * x1
            y1 = self.drawing_start[1] - self.drawing_scale * y1
            x2 = self.drawing_start[0] + self.drawing_scale * x2
            y2 = self.drawing_start[1] - self.drawing_scale * y2
            self.canvas.create_line(x1, y1, x2, y2, fill="red", width=2)

    def draw_beacons(self, beacons):
        self.canvas.delete('beacons')
        for beacon in beacons:
            id = str(beacon["id"])
            pos = beacon["pos"]
            x = self.drawing_start[0] + self.drawing_scale * pos[0]
            y = self.drawing_start[1] - self.drawing_scale * pos[1]
            covar = beacon["covar"]
            w, _ = np.linalg.eig(covar)
            width = 20000 * np.abs(w)
            # Coordinates for the ellipse
            x0 = x - width[0] / 2
            y0 = y - width[1] / 2
            x1 = x + width[0] / 2
            y1 = y + width[1] / 2
            self.canvas.create_oval(x0, y0, x1, y1, tags="beacons")
            self.canvas.create_text(x, y-15, text=id, tags="beacons")

def estimate_robot_pos(particleSet : ParticleSet, PgoodParticles):
    NgoodParticles = int(PgoodParticles*particleSet.M)
    best_indices = np.argsort(particleSet.weights)[-NgoodParticles:]
    weights = particleSet.weights[best_indices]
    sumWeights = np.sum(weights)
    positions = np.array(particleSet.set)[best_indices]
    meanPos = np.zeros((3,))
    for i in range(NgoodParticles):
        meanPos += (particleSet.weights[i]/sumWeights)*positions[i].x
    return meanPos

def estimate_beacons_pos(particleSet : ParticleSet, beacons: list):
    Nparticles = particleSet.M
    NknownBeacons = len(beacons)
    sumWeights = np.sum(particleSet.weights)
    #initialize beacons as dicts
    beacons = [{"id" : beacons[i], "pos" : np.zeros((2, )), "covar" : np.zeros((2, 2))} 
               for i in range(NknownBeacons)]
    for i in range(Nparticles):
        for j in range(NknownBeacons):
            beacons[j]["pos"] += (particleSet.weights[i]/sumWeights) * particleSet.set[i].features[j]["mean"]
            beacons[j]["covar"] += (particleSet.weights[i]/sumWeights) * particleSet.set[i].features[j]["covariance"]
    return beacons
            
        
    
def main():

    # Create an instance of the ArucoNode class
    node = FastSlamNode()
    node.animate.start_display()

    # Spin to keep the script for exiting
    rospy.spin()


if __name__ == '__main__':
    main()
