"""Encode selected source samples at the dataset timebase, then verify output."""
import json
import subprocess
from fractions import Fraction


def prepare_preview(source, output, row, view):
    m, q = row['manifest'], row['meta']
    fps = Fraction(m['sampling_fps_numerator'], m['sampling_fps_denominator'])
    rate = f'{fps.numerator}/{fps.denominator}'
    if view == 'oracle':
        indices = q['oracle_frame_indices_in_source']
        if len(set(indices)) != len(indices) or indices != sorted(indices):
            raise ValueError('Oracle source indices must be strictly increasing')
        selection = '+'.join(f'eq(n\\,{i})' for i in indices)
        count = len(indices)
    elif view == 'full':
        selection = f"between(n\\,{m['clip_start_frame']}\\,{m['clip_end_frame_exclusive']-1})"
        count = m['clip_frame_count']
    else:
        raise ValueError('Invalid preview view')
    filters = (f'fps=fps={rate}:start_time=0:round=near,select={selection},'
               f'setpts=N/({rate}*TB),scale=1280:960:force_original_aspect_ratio=decrease,'
               'pad=1280:960:(ow-iw)/2:(oh-ih)/2,setsar=1')
    subprocess.run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', str(source),
                    '-an', '-vf', filters, '-r', rate, '-fps_mode', 'cfr',
                    '-frames:v', str(count), '-c:v', 'libx264', '-preset', 'fast',
                    '-crf', '23', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    str(output)], check=True)
    probe = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_entries', 'stream=nb_read_frames,avg_frame_rate,duration',
        '-of', 'json', str(output)]))['streams'][0]
    actual = int(probe['nb_read_frames'])
    duration = float(probe['duration'])
    if actual != count or Fraction(probe['avg_frame_rate']) != fps:
        raise ValueError(f'Preview frame count/rate mismatch: {probe}')
    if abs(duration - float(count / fps)) > .001:
        raise ValueError('Preview duration does not match the dataset timebase')
    return {'frames': actual, 'fps': rate, 'duration_sec': duration}
