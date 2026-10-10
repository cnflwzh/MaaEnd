"""Site-specific entry/login/queue state belongs here, never in the controller.

There is deliberately no guessed Endfield login or queue automation. A loaded
page is not proof that its remote stream is ready. New providers need their own
observations and tests for input, scaling, codecs, Pointer Lock and background.
"""

from dataclasses import dataclass
from enum import Enum


class ServiceStage(str, Enum):
    PREVIEW = "preview_only"
    NEEDS_USER = "login_queue_or_start_requires_observation"
    STREAM_OBSERVED = "video_frames_observed_not_game_compatibility"


@dataclass(frozen=True)
class ManualServiceAdapter:
    name: str
    url: str
    allowed_origins: tuple[str, ...] = ()

    def stage(self, video_observations):
        if any(video.get("width", 0) > 0 and video.get("frames", 0) > 0 for video in video_observations):
            return ServiceStage.STREAM_OBSERVED
        return ServiceStage.NEEDS_USER


# Verified public, no-account sample, not an endorsed game provider. Selecting
# this adapter is explicit; the safe default is always the offline fixture.
EAGLE_PUBLIC_DEMO = ManualServiceAdapter(
    name="Eagle 3D public Unreal Pixel Streaming demo",
    url="https://connector.eagle3dstreaming.com/v5/demo/EpicPixelStreamingSample/E3DS-Iframe-Demo",
)
