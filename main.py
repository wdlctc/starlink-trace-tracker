import requests
from skyfield.api import Topos, load
import matplotlib.pyplot as plt
import numpy as np
import math

import time

import argparse

from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
import numpy as np
import starlink_grpc

def get_args():
    parser = argparse.ArgumentParser(description='Satellite Tracking')
    parser.add_argument('--url', action='store_true',
                        help='Download TLE data from default URL')
    parser.add_argument('--debug', action='store_true',
                        help='debug mode')
    parser.add_argument('--skipreboot', action='store_true',
                        help='skip reboot')
    return parser.parse_args()


def get_snr_data(time):

    context = starlink_grpc.ChannelContext()
    snr_data = starlink_grpc.obstruction_map(context)

    return snr_data

def polar_distance(a, b):
    r1, theta1 = a[0], a[1]
    r2, theta2 = b[0], b[1]
    delta_theta = np.pi - abs(abs(theta1 - theta2) - np.pi)
    return abs(r1 - r2) + delta_theta

def polar_to_cartesian(r, theta):
    x = r * np.cos(theta)
    y = r * np.sin(theta)
    return np.array([x, y])

def cartesian_to_polar(x, y):
    r = math.sqrt(x**2 + y**2)
    theta = math.atan2(y, x)
    if theta < 0:
        theta += 2 * math.pi
    return r, theta

def diff(array1, array2):
    difference = []
    for i in range(len(array1)):
        for j in range(len(array1[0])):
            if array1[i][j] != array2[i][j]:
                # transfer 2d array to polar coordinates
                y = 62 - i
                x = j - 62
                r, theta = cartesian_to_polar(y,x)

                difference.append((r, theta))
    return difference

def main():
    
    args = get_args()

    if args.url:
        default_url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle"

        # Use requests to download the data
        response = requests.get(default_url)

        # Check that the request was successful
        if response.status_code == 200:
            # Save the content to a local file
            with open('starlink.txt', 'w') as file:
                file.write(response.text)
        else:
            print(f"Failed to download data, status code: {response.status_code}")
            exit()

    if not args.skipreboot:
        # reboot starlink dish
        context = starlink_grpc.ChannelContext()
        starlink_grpc.reboot(context)

        # Wait for 1 minute for the dish to reboot
        print("Dish rebooted, waiting for 3 minutes ...")
        time.sleep(180)

    # Specify the TLE data file+
    tle_file = 'starlink.txt'

    # Load starlink TLE data
    satellites = load.tle_file(tle_file)
    context = starlink_grpc.ChannelContext()

    # Specify your location (from the starlink context)
    location = starlink_grpc.get_location(context)
    my_location = Topos(location.lla.lat, location.lla.lon, elevation_m=location.lla.alt)

    # Get the current time
    ts = load.timescale()

    snr_data_array = []
    timeline = []

    # Loop until we get a result
    while True:
        # Get current time
        current_time = time.localtime()

        # Check if it's exactly on the half hour or hour
        if current_time.tm_sec % 15 == 14:
            t = ts.now()
            snr_data = get_snr_data(current_time)

            timeline.append(t)
            snr_data_array.append(snr_data)


            # print(t.utc_datetime())

            if len(snr_data_array) >= 2:
                # get the measure_trace between two snr data
                measure_trace = diff(snr_data_array[-2], snr_data_array[-1])

                times = ts.linspace(timeline[-2], timeline[-1], num=15)

                
                min_distance = 100000
                min_index = 0
                all_trace = []
                all_sat = []
                for sat in satellites:
                    difference = sat - my_location
                    sat_trace = []

                    # bypass the satellite which is below 40 degree
                    # extract the satellite trace which is above 40 degree
                    bypass = False
                    for t in times:
                        topocentric = difference.at(t)
                        alt, az, distance = topocentric.altaz()
                        if alt.degrees > 30:
                            sat_trace.append((90 - alt.degrees, np.radians(az.degrees)))
                        else:
                            bypass = True
                            break
                    if bypass:
                        continue

                    if len(sat_trace) > 0:
                        # sort the satellite trace
                        sat_trace = sorted(sat_trace, key=lambda point: point[0]*math.cos(point[1]))

                        # calculate the distance between the difference and satellite trace
                        sat_trace = np.array(sat_trace)
                        sequence_1_cartesian = np.array([polar_to_cartesian(r, theta) for r, theta in measure_trace])
                        sequence_2_cartesian = np.array([polar_to_cartesian(r, theta) for r, theta in sat_trace])
                        distance, path = fastdtw(sequence_1_cartesian, sequence_2_cartesian, dist=euclidean)
                        all_trace.append(sat_trace)
                        all_sat.append(sat)
                        if abs(distance) < min_distance:
                            min_distance = abs(distance)
                            best_sat = sat
                            best_path = path
                            best_sat_trace = sat_trace
                            
                    if args.debug:
                        print(sat.name)
                        print(sat_trace)
                        print(distance)

                if args.debug:
                    print(measure_trace)

                    
                print("from " + str(timeline[-1].utc_datetime()) + " to " + str(timeline[-2].utc_datetime())) 
                print("best match satellite is: " + best_sat.name)

            
                # Set up the plot
                # fig = plt.figure()
                fig, axs = plt.subplots(1, 3, subplot_kw={'polar': True}, figsize=(15, 6))
                axs = np.array([axs])
                ax0 = axs[0,0]

                # ax = fig.add_subplot(111, polar=True)
                ax0.set_theta_zero_location("N")
                ax0.set_theta_direction(-1)
                ax0.set_rlim(90, 0)  # limit the radius to go from 90 to 0
                ax0.grid(True)

                ax1 = axs[0,1]

                # ax = fig.add_subplot(111, polar=True)
                ax1.set_theta_zero_location("N")
                ax1.set_theta_direction(-1)
                ax1.set_rlim(90, 0)  # limit the radius to go from 90 to 0
                ax1.grid(True)

                
                ax2 = axs[0,2]
                # ax = fig.add_subplot(111, polar=True)
                ax2.set_theta_zero_location("N")
                ax2.set_theta_direction(-1)
                ax2.set_rlim(90, 0)  # limit the radius to go from 90 to 0
                ax2.grid(True)

                # Plot the measure_trace
                measure_trace = np.array(measure_trace)
                ax0.scatter(measure_trace[:,1], 90-measure_trace[:,0], label="measure_trace")

                # Plot the best satellite trace
                best_sat_trace = np.array(best_sat_trace)
                ax1.scatter(best_sat_trace[:,1], 90-best_sat_trace[:,0], 
                            label= best_sat.name)
                
                for trace, sat in zip(all_trace, all_sat):
                    ax2.scatter(trace[:,1], 90-trace[:,0], label= sat.name)

                # Plot the path
                ax0.set_title('SNR Difference')
                ax1.set_title('match Satellite Trace')
                ax2.set_title('Starlink Satellite Trace')
                ax0.legend(loc='upper right', bbox_to_anchor=(1.4, 1))
                ax1.legend(loc='upper right', bbox_to_anchor=(1.4, 1))
                ax2.legend(loc='upper right', bbox_to_anchor=(1.4, 1))
                # plt.show()# Save the figure
                plt.savefig('figures/starlink_match_plots' + " from " + str(timeline[-1].utc_datetime()) + " to " + str(timeline[-2].utc_datetime()) + '.png')
                plt.close(fig)


            if len(snr_data_array) >= 60:
                break
            
        # Sleep for 1 second to prevent constant checking
        time.sleep(1)

if __name__ == "__main__":
    main()