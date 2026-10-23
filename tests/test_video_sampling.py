from io import BytesIO
from PIL import Image
import pytest
from app.production.video_sampling import sample_video
from tests.test_video_files import make_video


def test_samples_actual_decoded_frames_and_timestamps():
    samples = sample_video(make_video(), 'video/mp4', 4)
    assert [s['at_ms'] for s in samples] == [0, 300, 600, 900]
    for sample in samples:
        with Image.open(BytesIO(sample['data'])) as image:
            assert image.format == 'JPEG' and max(image.size) <= 640


def test_short_clip_never_invents_extra_distinct_frames():
    assert len(sample_video(make_video(2), 'video/mp4', 12)) == 2


@pytest.mark.parametrize('count', [0, 13, True])
def test_bad_count_rejected(count):
    with pytest.raises(ValueError): sample_video(make_video(), 'video/mp4', count)


def test_bad_video_rejected():
    with pytest.raises(ValueError): sample_video(b'fake video', 'video/mp4', 4)
