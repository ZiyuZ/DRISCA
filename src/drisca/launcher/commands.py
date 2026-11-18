"""实验指令定义和参数。"""

from pydantic import BaseModel, ConfigDict


class AutopilotParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    enabled: bool


class TakeoverParams(AutopilotParams):
    speech: str


class WeatherPresetParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    preset: str


class SpeechParams(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    text: str


MODELS = {
    'autopilot': AutopilotParams,
    'takeover': TakeoverParams,
    'weather': WeatherPresetParams,
    'speech': SpeechParams,
}
COMMANDS = [
    {
        'id': 'autopilot',
        'label': '自动驾驶',
        'description': '设置自动驾驶',
        'fields': [{'key': 'enabled', 'label': '启用', 'type': 'boolean', 'required': True, 'default': True}],
    },
    {
        'id': 'takeover',
        'label': '接管请求',
        'description': '发送接管请求并播放语音',
        'fields': [
            {'key': 'enabled', 'label': '启用', 'type': 'boolean', 'required': True, 'default': True},
            {'key': 'speech', 'label': '语音内容', 'type': 'text', 'required': True, 'default': ''},
        ],
    },
    {
        'id': 'weather',
        'label': '天气切换',
        'description': '切换天气预设',
        'fields': [
            {'key': 'preset', 'label': '天气预设', 'type': 'text', 'required': True, 'default': 'ClearNoon'}
        ],
    },
    {
        'id': 'speech',
        'label': '语音播放',
        'description': '播放语音',
        'fields': [{'key': 'text', 'label': '语音内容', 'type': 'text', 'required': True, 'default': ''}],
    },
]
