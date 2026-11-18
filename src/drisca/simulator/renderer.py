"""驾驶画面合成。"""

from collections.abc import Mapping

import carla
import pygame

from drisca.core.config import DisplayConfig, DisplayLayoutConfig


class ViewportRenderer:
    def __init__(self, display_cfg: DisplayConfig) -> None:
        pygame.display.init()
        flags = (pygame.FULLSCREEN if display_cfg.fullscreen else 0) | (
            pygame.NOFRAME if display_cfg.borderless else 0
        )
        self.surface = pygame.display.set_mode(display_cfg.resolution, flags)
        self.layout = display_cfg.layout

    @property
    def actual_resolution(self) -> tuple[int, int]:
        return self.surface.get_size()

    def update_layout(self, layout: DisplayLayoutConfig) -> None:
        self.layout = layout

    def render_frame(self, images: Mapping[str, carla.Image | None]) -> None:
        self.surface.fill((0, 0, 0))
        width, height = self.actual_resolution
        for name in ('front', 'rear_top', 'rear_left', 'rear_right'):
            if name != 'front' and not self.layout.show_rearview:
                continue
            image = images[name]
            if image is None:
                continue
            pixels = pygame.image.frombuffer(image.raw_data, (image.width, image.height), 'BGRA')
            pixels.set_alpha(None)
            position = (0.5, 0.5) if name == 'front' else getattr(self.layout, name).screen_position
            center = (round(position[0] * width), round(position[1] * height))
            self.surface.blit(pixels, pixels.get_rect(center=center))
        pygame.display.flip()

    def close(self) -> None:
        pygame.display.quit()
