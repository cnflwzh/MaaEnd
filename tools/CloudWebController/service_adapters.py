"""Site-specific entry/login/queue state belongs here, never in the controller.

There is deliberately no guessed Endfield login or queue automation. A loaded
page is not proof that its remote stream is ready. New providers need their own
observations and tests for input, scaling, codecs, Pointer Lock and background.
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

ENDFIELD_CLOUD_URL = "https://endfield.hypergryph.com/cloud"


def is_endfield_cloud(url):
    if not url:
        return False
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname == "endfield.hypergryph.com" and parsed.path.rstrip("/") == "/cloud"


# Observed in the official first-login flow. Read only bounded, non-sensitive
# state: never return page text, input values, URLs, storage or authentication.
# A homepage/promotional video is not the game stream. Queue UI has not been
# observed and is deliberately not inferred from a loaded document.
ENDFIELD_OBSERVATION = """(() => {
  const video = document.getElementById('WelinkGameVideo');
  const visible = e => !!e && e.getClientRects().length > 0 &&
    getComputedStyle(e).visibility !== 'hidden';
  const text = document.body?.innerText || '';
  const login = Array.from(document.querySelectorAll('button')).some(
    e => visible(e) && e.textContent.trim() === '注册/登录');
  return {
    login,
    reconnecting: text.includes('游戏正在重连中'),
    starting: text.includes('正在检测网络环境') || text.includes('游戏启动中，请耐心等待'),
    playable: visible(video) && video.readyState >= 2 &&
      video.videoWidth > 0 && video.videoHeight > 0 && !video.paused && !video.error,
    clock: video && Number.isFinite(video.currentTime) ? video.currentTime : 0
  };
})()"""


class ServiceStage(StrEnum):
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
