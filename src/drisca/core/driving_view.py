"""键盘动作到 Unreal FKey 名称的映射。"""

from drisca.core.config import KeyboardControlConfig, KeyboardKey

KEYBOARD_FKEYS: dict[KeyboardKey, str] = {
    KeyboardKey.ESCAPE: 'Escape',
    KeyboardKey.P: 'P',
    KeyboardKey.BACKSLASH: 'Backslash',
    KeyboardKey.Q: 'Q',
    KeyboardKey.M: 'M',
    KeyboardKey.PERIOD: 'Period',
    KeyboardKey.COMMA: 'Comma',
    KeyboardKey.SPACE: 'SpaceBar',
    KeyboardKey.SEMICOLON: 'Semicolon',
    KeyboardKey.K: 'K',
    KeyboardKey.L: 'L',
    KeyboardKey.Z: 'Z',
    KeyboardKey.X: 'X',
    KeyboardKey.I: 'I',
    KeyboardKey.UP: 'Up',
    KeyboardKey.DOWN: 'Down',
    KeyboardKey.LEFT: 'Left',
    KeyboardKey.RIGHT: 'Right',
    KeyboardKey.W: 'W',
    KeyboardKey.S: 'S',
    KeyboardKey.A: 'A',
    KeyboardKey.D: 'D',
    KeyboardKey.KEYPAD_1: 'NumPadOne',
    KeyboardKey.KEYPAD_2: 'NumPadTwo',
}


def keyboard_mapping(config: KeyboardControlConfig) -> dict[str, str]:
    """将功能名到 KeyboardKey 的配置转换为 Unreal FKey 名称。"""
    return {name: KEYBOARD_FKEYS[key] for name, key in config if key != KeyboardKey.UNBOUND}
