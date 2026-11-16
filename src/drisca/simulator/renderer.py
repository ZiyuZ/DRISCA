"""驾驶画面合成。"""

from collections.abc import Mapping

import carla
import pygame

from drisca.core.config import CameraConfig, CameraRigConfig, DisplayConfig


class ViewportRenderer:
    def __init__(self, display_cfg: DisplayConfig, camera_rig_cfg: CameraRigConfig) -> None:
        pygame.display.init()
        flags = (pygame.FULLSCREEN if display_cfg.fullscreen else 0) | (
            pygame.NOFRAME if display_cfg.borderless else 0
        )
        self.surface = pygame.display.set_mode(display_cfg.resolution, flags)
        self.cameras = {
            name: getattr(camera_rig_cfg, name) for name in ('front', 'rear_top', 'rear_left', 'rear_right')
        }
        self.show_rearview = camera_rig_cfg.show_rearview

    @property
    def actual_resolution(self) -> tuple[int, int]:
        return self.surface.get_size()

    def set_rearview_visible(self, visible: bool) -> None:
        self.show_rearview = visible

    def update_camera_mount(self, camera_name: str, mount: CameraConfig) -> None:
        self.cameras[camera_name] = mount

    def render_frame(self, images: Mapping[str, carla.Image | None]) -> None:
        self.surface.fill((0, 0, 0))
        width, height = self.actual_resolution
        for name, config in self.cameras.items():
            if name != 'front' and not self.show_rearview:
                continue
            image = images[name]
            if image is None:
                continue
            pixels = pygame.image.frombuffer(image.raw_data, (image.width, image.height), 'BGRA')
            center = (round(config.screen_position[0] * width), round(config.screen_position[1] * height))
            self.surface.blit(pixels, pixels.get_rect(center=center))
        pygame.display.flip()

    def close(self) -> None:
        pygame.display.quit()
