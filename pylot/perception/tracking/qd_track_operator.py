import cv2

import erdos

import numpy as np

from pylot.perception.detection.obstacle import Obstacle
from pylot.perception.detection.utils import BoundingBox2D, \
    BoundingBox3D, OBSTACLE_LABELS
from pylot.perception.messages import ObstaclesMessage

import torch

class QdTrackOperator(erdos.Operator):
    def __init__(self, camera_stream, obstacle_tracking_stream, flags,
                 camera_setup):
        from qdtrack.apis import init_model

        camera_stream.add_callback(self.on_frame_msg,
                                   [obstacle_tracking_stream])
        self._flags = flags
        self._logger = erdos.utils.setup_logging(self.config.name,
                                                 self.config.log_file_name)
        self._csv_logger = erdos.utils.setup_csv_logging(
            self.config.name + '-csv', self.config.csv_log_file_name)
        self._camera_setup = camera_setup
        self.model = init_model(self._flags.qd_track_config_path, checkpoint=self._flags.qd_track_model_path, device='cuda:0', cfg_options=None)
        self.classes = ('pedestrian', 'rider', 'car', 'bus', 'truck', 'bicycle', 'motorcycle', 'train')
        self.frame_id = 0

    @staticmethod
    def connect(camera_stream):
        obstacle_tracking_stream = erdos.WriteStream()
        return [obstacle_tracking_stream]

    def destroy(self):
        self._logger.warn('destroying {}'.format(self.config.name))

    @erdos.profile_method()
    def on_frame_msg(self, msg, obstacle_tracking_stream):
        """Invoked when a FrameMessage is received on the camera stream."""
        from qdtrack.apis import inference_model

        self._logger.debug('@{}: {} received frame'.format(
            msg.timestamp, self.config.name))
        assert msg.frame.encoding == 'BGR', 'Expects BGR frames'

        image_np = msg.frame.as_bgr_numpy_array()
        results = inference_model(self.model, image_np, self.frame_id)
        bbox_result, track_result = results.values()
        track_bboxes = np.zeros((0, 5))
        track_ids = np.zeros((0))
        track_labels = np.zeros((0))
        obstacle_count = 0
        for k, v in track_result.items():
            track_bboxes = np.concatenate((track_bboxes, v['bbox'][None, :]), axis=0)
            track_ids = np.concatenate((track_ids, np.array([k])), axis=0)
            track_labels = np.concatenate((track_labels, np.array([v['label']])))
            obstacle_count += 1
        obstacles = []
        for i in range(obstacle_count):
            track_id = track_ids[i]
            bbox = track_bboxes[i, :]
            score = bbox[4]
            label_id = track_labels[i]
            label = self.classes[int(label_id)]

            if label in ['pedestrian', 'rider']:
                label = 'person'
    
            if label in OBSTACLE_LABELS:
                bounding_box_2D = BoundingBox2D(bbox[0], bbox[2], bbox[1],
                                                bbox[3])
                bounding_box_3D = None
                obstacles.append(
                    Obstacle(bounding_box_2D,
                             score,
                             label,
                             track_id,
                             bounding_box_2D=bounding_box_2D))
        obstacle_tracking_stream.send(
            ObstaclesMessage(msg.timestamp, obstacles, 0))
