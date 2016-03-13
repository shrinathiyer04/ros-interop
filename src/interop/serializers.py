# -*- coding: utf-8 -*-

"""Interoperability API message serializer."""

import utm
import rospy
import dateutil.parser
from dateutil.tz import tzutc
from datetime import datetime
from visualization_msgs.msg import Marker, MarkerArray
from std_msgs.msg import ColorRGBA, Header, String, Time


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


class ServerInfoDeserializer(object):

    """Server information deserializer."""

    @classmethod
    def from_json(cls, json):
        """Deserializes server information into a tuple of standard ROS
        messages.

        Args:
            json: JSON dictionary.

        Returns:
            (std_msgs/String, std_msgs/Time, std_msgs/Time) tuple.
            The first is the server message, the second is the message
            timestamp and the last is the server time.
        """
        message = String(data=json["message"])
        message_timestamp = iso8601_to_rostime(json["message_timestamp"])
        server_time = iso8601_to_rostime(json["server_time"])

        return (message, message_timestamp, server_time)


class ObstaclesDeserializer(object):

    """Obstacles message deserializer."""

    # Rate to display obstacles in Hz.
    RATE = 10

    # McGill Robotics red, because we have big egos.
    OBSTACLE_COLOR = ColorRGBA(
        r=218 / 255.0,
        g=41 / 255.0,
        b=28 / 255.0,
        a=1.0)

    @classmethod
    def from_json(cls, json):
        """Deserializes obstacle data into two MarkerArrays.

        Args:
            json: JSON dictionary.

        Returns:
            Tuple of two visualization_msgs/MarkerArray, MarkerArray) tuple.
            The first is of moving obstacles, and the latter is of stationary
            obstacles.
        """
        # Generate base header.
        header = Header()
        header.stamp = rospy.get_rostime()
        header.frame_id = "odom"

        # Parse moving obstacles, and populate markers with spheres.
        moving_obstacles = MarkerArray()
        if "moving_obstacles" in json:
            for obj in json["moving_obstacles"]:
                # Moving obstacles are spheres.
                marker = Marker()
                marker.header = header
                marker.type = marker.SPHERE
                marker.color = cls.OBSTACLE_COLOR
                marker.ns = "stationary_obstacles"
                marker.lifetime = rospy.Duration(1.0 / cls.RATE)

                # Set scale as radius.
                radius = feet_to_meters(obj["sphere_radius"])
                marker.scale.x = marker.scale.y = marker.scale.z = radius

                # Convert latitude and longitude to UTM.
                easting, northing, _, _ = utm.from_latlon(obj["latitude"],
                                                          obj["longitude"])
                marker.pose.position.x = easting
                marker.pose.position.y = northing
                marker.pose.position.z = feet_to_meters(obj["altitude_msl"])

                moving_obstacles.markers.append(marker)

        # Parse stationary obstacles, and populate markers with cylinders.
        stationary_obstacles = MarkerArray()
        if "stationary_obstacles" in json:
            for obj in json["stationary_obstacles"]:
                # Stationary obstacles are cylinders.
                marker = Marker()
                marker.header = header
                marker.type = marker.CYLINDER
                marker.color = cls.OBSTACLE_COLOR
                marker.ns = "stationary_obstacles"
                marker.lifetime = rospy.Duration(1.0 / cls.RATE)

                # Set scale to define size.
                radius = feet_to_meters(obj["cylinder_radius"])
                height = feet_to_meters(obj["cylinder_height"])
                marker.scale.x = marker.scale.y = radius
                marker.scale.z = height

                # Convert latitude and longitude to UTM.
                easting, northing, _, _ = utm.from_latlon(obj["latitude"],
                                                          obj["longitude"])
                marker.pose.position.x = easting
                marker.pose.position.y = northing
                marker.pose.position.z = height / 2

                stationary_obstacles.markers.append(marker)

        return (moving_obstacles, stationary_obstacles)


class TelemetrySerializer(object):

    """Telemetry message serializer."""

    @classmethod
    def from_msg(cls, navsat_msg, compass_msg):
        """Serializes telemetry data into a dictionary.

        Args:
            navsat_msg: sensor_msgs/NavSatFix message.
            compass_msg: std_msgs/Float64 message in degrees.

        Returns:
            JSON dictionary.
        """
        return {
            "latitude": float(navsat_msg.latitude),
            "longitude": float(navsat_msg.longitude),
            "altitude_msl": meters_to_feet(navsat_msg.altitude),
            "uas_heading": float(compass_msg.data)
        }


class TargetSerializer(object):

    """Target message serializer."""

    @classmethod
    def from_msg(cls, msg):
        """Serializes target data into a dictionary.

        Args:
            msg: Some ROS message (TBD).

        Returns:
            JSON dictionary.
        """
        raise NotImplementedError()

    @classmethod
    def from_json(cls, json):
        """Deserializes target data into relevant ROS message.

        Args:
            json: JSON dictionary.

        Returns:
            Some ROS message (TBD).
        """
        raise NotImplementedError()


if __name__ == "__main__":
    from std_msgs.msg import Float64
    from sensor_msgs.msg import NavSatFix

    # Initialize node for ROS time to be set.
    rospy.init_node("test_interop_serializers")

    # Test our server info deserializer.
    server_info = {
        "message": "Fly Safe",
        "message_timestamp": "2015-06-14 18:18:55.642000+00:00",
        "server_time": "2015-08-14 03:37:13.331402"
    }
    print(ServerInfoDeserializer.from_json(server_info))

    # Test out obstacles deserializer.
    obstacles = {
        "moving_obstacles": [
            {
                "altitude_msl": 189.56748784643966,
                "latitude": 38.141826869853645,
                "longitude": -76.43199876559223,
                "sphere_radius": 150.0
             },
            {
                "altitude_msl": 250.0,
                "latitude": 38.14923628783763,
                "longitude": -76.43238529543882,
                "sphere_radius": 150.0
            }
        ],
        "stationary_obstacles": [
            {
                "cylinder_height": 750.0,
                "cylinder_radius": 300.0,
                "latitude": 38.140578,
                "longitude": -76.428997
            },
            {
                "cylinder_height": 400.0,
                "cylinder_radius": 100.0,
                "latitude": 38.149156,
                "longitude": -76.430622
            }
        ]
    }
    print(ObstaclesDeserializer.from_json(obstacles))

    # Test out telemetry serializer.
    print(TelemetrySerializer.from_msg(NavSatFix(), Float64(120)))