import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from app.media import prepare_preview


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class MediaTests(unittest.TestCase):
    def test_final_sample_inside_source_duration_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'edge.avi'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                            'nullsrc=s=64x48:r=25:d=1.12,geq=lum=16+2*N:cb=128:cr=128',
                            '-c:v', 'ffv1', str(source)], check=True)
            references = {}
            for action in ('round', 'pass'):
                sampled = subprocess.check_output([
                    'ffmpeg', '-v', 'error', '-i', str(source), '-vf',
                    f'fps=3:start_time=0:round=near:eof_action={action},format=gray',
                    '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
                references[action] = list(sampled[::64*48])
            self.assertEqual(len(references['round']), 3)
            self.assertEqual(len(references['pass']), 4)
            self.assertEqual(references['round'], references['pass'][:3])
            row = {'manifest': {'sampling_fps_numerator': 3,
                               'sampling_fps_denominator': 1,
                               'clip_start_frame': 1, 'clip_end_frame_exclusive': 4,
                               'clip_frame_count': 3},
                   'meta': {'oracle_frame_indices_in_source': [0, 3]}}
            for view, indices in [('full', [1, 2, 3]), ('oracle', [0, 3])]:
                with self.subTest(view=view):
                    output = Path(directory) / (view + '.mp4')
                    info = prepare_preview(source, output, row, view)
                    self.assertEqual(info['frames'], len(indices))
                    self.assertAlmostEqual(info['duration_sec'], len(indices)/3, places=5)
                    pixels = subprocess.check_output([
                        'ffmpeg', '-v', 'error', '-i', str(output), '-vf',
                        'format=gray,crop=1:1:640:480', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
                    for actual, index in zip(pixels, indices):
                        self.assertLessEqual(abs(actual-references['pass'][index]), 2)
            row['manifest'].update(clip_end_frame_exclusive=5, clip_frame_count=4)
            with self.assertRaisesRegex(ValueError, 'frame count/rate mismatch'):
                prepare_preview(source, Path(directory)/'beyond-source.mp4', row, 'full')

    def test_native_25fps_samples_keep_order_and_3fps_timebase(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'ramp.avi'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                            'nullsrc=s=64x48:r=25:d=4,geq=lum=16+2*N:cb=128:cr=128',
                            '-c:v', 'ffv1', str(source)], check=True)
            sampled = subprocess.check_output([
                'ffmpeg', '-v', 'error', '-i', str(source), '-vf',
                'fps=3:start_time=0:round=near,format=gray', '-fps_mode', 'passthrough',
                '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
            reference = list(sampled[::64*48])
            self.assertEqual(len(reference), 12)
            row = {'manifest': {'sampling_fps_numerator': 3,
                               'sampling_fps_denominator': 1,
                               'clip_start_frame': 1, 'clip_end_frame_exclusive': 10,
                               'clip_frame_count': 9},
                   'meta': {'oracle_frame_indices_in_source': [0, 3, 7, 11]}}
            for view, indices in [('full', list(range(1, 10))), ('oracle', [0, 3, 7, 11])]:
                with self.subTest(view=view):
                    output = Path(directory) / (view + '.mp4')
                    info = prepare_preview(source, output, row, view)
                    self.assertEqual(info['frames'], len(indices))
                    self.assertAlmostEqual(info['duration_sec'], len(indices)/3, places=5)
                    pixels = subprocess.check_output([
                        'ffmpeg', '-v', 'error', '-i', str(output), '-vf',
                        'format=gray,crop=1:1:640:480', '-fps_mode', 'passthrough',
                        '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
                    self.assertEqual(len(pixels), len(indices))
                    for actual, index in zip(pixels, indices):
                        self.assertLessEqual(abs(actual-reference[index]), 2)
