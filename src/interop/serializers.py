# -*- coding: utf-8 -*-
"""Interoperability API message serializer.
Serializes from ROS messages to python dictionaries and vice versa."""

import cv2
import rospy
import numpy as np
import dateutil.parser
import tf.transformations
from dateutil.tz import tzutc
from datetime import datetime
from cv_bridge import CvBridge
from sensor_msgs.msg import CompressedImage
from geographic_msgs.msg import GeoPointStamped, GeoPoint
from std_msgs.msg import Header, Time
from interop.msg import (Color, FlyZone, FlyZoneArray, Orientation, Shape,
                         Object, ObjectType, GeoCylinder, GeoPolygonStamped,
                         GeoCylinderArrayStamped, WayPoints)


def meters_to_feet(m):
    """Converts a distance from meters to feet.

    Args:
        m: Distance in meters.

    Returns:
        Distance in feet.
    """
    return float(m) / 0.3048


def feet_to_meters(ft):
    """Converts a distance from feet to meters.

    Args:
        ft: Distance in feet.

    Returns:
        Distance in meters.
    """
    return float(ft) * 0.3048


def iso8601_to_rostime(iso):
    """Converts ISO 8601 time to ROS Time.

    Args:
        iso: ISO 8601 encoded string.

    Returns:
        std_msgs/Time.
    """
    # Convert to datetime in UTC.
    t = dateutil.parser.parse(iso)
    if not t.utcoffset():
        t = t.replace(tzinfo=tzutc())

    # Convert to time from epoch in UTC.
    epoch = datetime.utcfromtimestamp(0)
    epoch = epoch.replace(tzinfo=tzutc())
    dt = t - epoch

    # Create ROS message.
    time = Time()
    time.data.secs = int(dt.total_seconds())
    time.data.nsecs = dt.microseconds * 1000

    return time


class MissionDeserializer(object):

    """Mission information deserializer."""

    @classmethod
    def __get_flyzone(cls, data, frame):
        """
        Deserializes flight boundary data into a FlyZoneArray message.

        Args:
            data: List of dictionaries.
            frame: Frame id for the boundaries.

        Returns:
            A FlyzoneArray message type which contains an array of FlyZone
            messages, which contains a polygon for the boundary, a max
            altitude and a min altitude.
        """
        # Generate header for all zones.
        header = Header()
        header.stamp = rospy.get_rostime()
        header.frame_id = frame

        flyzones = FlyZoneArray()
        for zone in data:
            flyzone = FlyZone()
            flyzone.zone.header = header

            flyzone.max_alt = feet_to_meters(zone["altitude_msl_max"])
            flyzone.min_alt = feet_to_meters(zone["altitude_msl_min"])

            # Change boundary points to ros message of type polygon.
            for waypoint in zone["boundary_pts"]:
                point = GeoPoint()
                point.latitude = waypoint["latitude"]
                point.longitude = waypoint["longitude"]
                flyzone.zone.polygon.points.append(point)

            flyzones.flyzones.append(flyzone)

        return flyzones

    @classmethod
    def __get_waypoints(cls, data, frame):
        """
        Deserializes a list of waypoints into a marker message.

        Args:
            data: List of dictionaries corresponding to waypoints.
            frame: Frame of the markers.

        Returns:
            A marker message of type Points, with a list of points in order
            corresponding to each waypoint.
        """
        header = Header()
        header.stamp = rospy.get_rostime()
        header.frame_id = frame

        waypoints = WayPoints()
        waypoints.header = header

        # Ensure there is no rotation by setting w to 1.
        for point in data:
            waypoint = GeoPoint()

            altitude = feet_to_meters(point["altitude_msl"])

            waypoint.latitude = point["latitude"]
            waypoint.longitude = point["longitude"]
            waypoint.altitude = altitude

            waypoints.waypoints.append(waypoint)

        return waypoints

    @classmethod
    def __get_search_grid(cls, data, frame):
        """
        Deserializes a the search grid into a polygon message.

        Args:
            data: List of dictionaries corresponding to the search grid points.
            frame: Frame for the polygon.

        Returns:
            Message of type PolygonStamped with the bounds of the search grid.
        """
        header = Header()
        header.stamp = rospy.get_rostime()
        header.frame_id = frame

        search_grid = GeoPolygonStamped()
        search_grid.header = header

        for point in data:
            boundary_pnt = GeoPoint()

            altitude = feet_to_meters(point["altitude_msl"])

            boundary_pnt.latitude = point["latitude"]
            boundary_pnt.longitude = point["longitude"]
            boundary_pnt.altitude = altitude

            search_grid.polygon.points.append(boundary_pnt)

        return search_grid

    @classmethod
    def __get_point_msg(cls, data, frame):
        """
        Deserializes a location to a message of type PointStamped.

        Args:
            data: A dictionary containing the location.
            frame: Frame for the point.

        Returns:
            A message of type PointStamped with the location.
        """
        header = Header()
        header.stamp = rospy.get_rostime()
        header.frame_id = frame

        msg = GeoPointStamped()
        msg.header = header

        msg.position.latitude = data["latitude"]
        msg.position.longitude = data["longitude"]

        return msg

    @classmethod
    def from_dict(cls, data, frame):
        """
        Deserializes the mission object from a dictionary to several
        ros messages.

        Args:
            data: A dictionary.
            frame: frame id for the messages.

        Returns:
            A tuple of (FlyZoneArray, GeoPolygonStamped, WayPoints,
            GeoPointStamped, GeoPointStamped, GeoPointStamped, GeoPointStamped)
            corresponding to the flyzones, search grid, waypoints, air drop
            position, off axis object location, the emergent object location,
            and the home position.
        """
        flyzones = cls.__get_flyzone(data["fly_zones"], frame)
        search_grid = cls.__get_search_grid(data["search_grid_points"], frame)
        waypoints = cls.__get_waypoints(data["mission_waypoints"], frame)
        air_drop = cls.__get_point_msg(data["air_drop_pos"], frame)
        off_axis_obj = cls.__get_point_msg(data["off_axis_odlc_pos"], frame)
        emergent_obj = cls.__get_point_msg(data["emergent_last_known_pos"],
                                           frame)
        home = cls.__get_point_msg(data["home_pos"], frame)

        return (flyzones, search_grid, waypoints, air_drop, off_axis_obj,
                emergent_obj, home)


class ObstaclesDeserializer(object):

    """Obstacles message deserializer."""

    @classmethod
    def from_dict(cls, data, frame, lifetime):
        """Deserializes obstacle data.

        Args:
            data: A dictionary.
            frame: Frame ID of every Marker.
            lifetime: Lifetime of every Marker in seconds.

        Returns:
            GeoCylinderArrayStamped stationary obstacles.
        """
        # Generate base header.
        header = Header()
        header.stamp = rospy.get_rostime()
        header.frame_id = frame

        # Parse stationary obstacles, and populate markers with cylinders.
        stationary_obstacles = GeoCylinderArrayStamped()
        stationary_obstacles.header = header
        if "stationary_obstacles" in data:
            for obj in data["stationary_obstacles"]:
                # Stationary obstacles are cylinders.
                obstacle = GeoCylinder()

                # Set scale to define size.
                obstacle.radius = feet_to_meters(obj["cylinder_radius"])
                obstacle.height = feet_to_meters(obj["cylinder_height"])

                obstacle.center.latitude = obj["latitude"]
                obstacle.center.longitude = obj["longitude"]

                stationary_obstacles.cylinders.append(obstacle)

        return stationary_obstacles


class TelemetrySerializer(object):

    """Telemetry message serializer."""

    @classmethod
    def from_msg(cls, navsat_msg, altitude_msg, pose_msg):
        """Serializes telemetry data into a dictionary.

        Args:
            navsat_msg: sensor_msgs/NavSatFix message.
            altitude_msg: mavros_msgs/Altitude message.
            pose_msg: geometry_msgs/PoseStamped message in ENU.

        Returns:
            A dictionary.
        """
        # Convert orientation from east to north.
        q = [
            pose_msg.pose.orientation.x,
            pose_msg.pose.orientation.y,
            pose_msg.pose.orientation.z,
            pose_msg.pose.orientation.w,
        ]
        yaw = tf.transformations.euler_from_quaternion(q)[2]
        compass_heading = (450 - np.rad2deg(yaw)) % 360

        return {
            "latitude": float(navsat_msg.latitude),
            "longitude": float(navsat_msg.longitude),
            "altitude_msl": meters_to_feet(altitude_msg.amsl),
            "uas_heading": float(compass_heading)
        }


class ObjectSerializer(object):

    """Object message serializer."""

    # Enumeration message types.
    ENUMERATION_TYPES = {Color, Orientation, Shape, ObjectType}

    @classmethod
    def from_msg(cls, msg):
        """Serializes object data into a dictionary.

        Args:
            msg: Object ROS message.

        Returns:
            A dictionary.
        """
        data = {}

        # Set all fields.
        for attribute in msg.__slots__:
            value = getattr(msg, attribute)
            if type(value) in cls.ENUMERATION_TYPES:
                value = value.data

            data[attribute] = value

        return data

    @classmethod
    def from_dict(cls, data):
        """Deserializes object data into Object ROS message.

        Args:
            data: A dictionary.

        Returns:
            A Object ROS message.
        """
        # Determine ROS message type.
        msg = Object()

        for attribute in msg.__slots__:
            if attribute in data:
                # Get corresponding type of slot.
                attribute_type = type(getattr(msg, attribute))

                # Set 'casted' value.
                value = data[attribute]
                if value is not None:
                    setattr(msg, attribute, attribute_type(value))

        return msg


class ObjectImageSerializer(object):

    """Object image message serializer."""

    @classmethod
    def from_msg(cls, msg):
        """Serializes a ROS Image message into a compressed PNG image.

        Args:
            msg: ROS Image or CompressedImage message.

        Returns:
            Compressed PNG image.

        Raises:
            CvBridgeError: On image conversion error.
        """
        if isinstance(msg, CompressedImage):
            # Decompress message.
            msg = cls.from_raw(msg.data)

        # Convert ROS Image to OpenCV image.
        bridge = CvBridge()
        img = bridge.imgmsg_to_cv2(msg)

        # Convert to PNG with highest level of compression to limit bandwidth
        # usage. PNG is used since it is a lossless format, so this can later
        # be retrieved as a ROS image without issue.
        compression = [cv2.IMWRITE_PNG_COMPRESSION, 9]
        png = cv2.imencode(".png", img, compression)[1].tostring()

        return png

    @classmethod
    def from_raw(cls, raw, compress=False):
        """Deserializes binary-encoded image data into a ROS Image message.

        Args:
            raw: Binary encoded image data.
            compress: Whether to return a compressed image or not.

        Returns:
            ROS Image or CompressedImage message.

        Raises:
            CvBridgeError: On image conversion error.
        """
        # Convert to OpenCV image.
        nparr = np.fromstring(raw, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # Convert to ROS message.
        bridge = CvBridge()
        msg = bridge.cv2_to_imgmsg(img)

        if compress:
            data = cls.from_msg(msg)
            msg = CompressedImage()
            msg.format = "png"
            msg.data = data

        return msg
