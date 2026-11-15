"""根据 CARLA PythonAPI 的 YAML 文档生成类型声明。"""

import argparse
import ast
import keyword
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def _type(value: object, module: str) -> str:
    """将文档中的类型转换成 Python 类型表达式。"""
    text = str(value or 'Any').strip()
    text = {'string': 'str', 'boolean': 'bool', 'integer': 'int', 'double': 'float'}.get(text, text)
    text = re.sub(r'\b(?:u?int(?:8|16|32|64)_t|unsigned int|long)\b', 'int', text)
    text = text.replace('carla.', '' if module == 'carla' else 'carla.')
    text = text.replace('command.', 'command.' if module == 'carla' else '')
    text = re.sub(r'\b(list|tuple|set|dict)\((.+)\)', r'\1[\2]', text)
    try:
        expression = ast.parse(text, mode='eval').body
    except SyntaxError:
        return 'Any'
    if not isinstance(expression, ast.Name | ast.Attribute | ast.Subscript | ast.BinOp):
        return 'Any'
    return text


def _name(value: object) -> str | None:
    name = str(value or '').split('(')[0].strip()
    return name if name.isidentifier() and not keyword.iskeyword(name) else None


def _render_class(data: dict[str, Any], module: str) -> list[str]:
    name = _name(data.get('class_name'))
    if name is None:
        return []
    parent = _type(data.get('parent'), module)
    base = f'({parent})' if parent != 'Any' else ''
    lines = [f'class {name}{base}:']
    members: list[str] = []
    for field in data.get('instance_variables') or []:
        field_name = _name(field.get('var_name'))
        if field_name:
            field_type = _type(field.get('type'), module)
            if module == 'carla' and name == 'WorldSettings' and field_name == 'fixed_delta_seconds':
                field_type = 'float | None'
            members.append(f'    {field_name}: {field_type}')
    methods: dict[str, str] = {}
    for method in data.get('methods') or []:
        method_name = _name(method.get('def_name'))
        if method_name is None:
            continue
        params = ['self']
        default_seen = False
        for param in method.get('params') or []:
            param_name = _name(param.get('param_name'))
            if param_name is None or param_name == 'self':
                continue
            has_default = 'default' in param or default_seen
            default_seen = has_default
            suffix = ' = ...' if has_default else ''
            params.append(f'{param_name}: {_type(param.get("type"), module)}{suffix}')
        result = 'None' if method_name == '__init__' else _type(method.get('return'), module)
        methods[method_name] = f'    def {method_name}({", ".join(params)}) -> {result}: ...'
    members.extend(methods.values())
    return lines + (members or ['    ...']) + ['']


def generate(docs_dir: Path, output_dir: Path) -> list[Path]:
    """读取文档目录中的 YAML，生成 carla 和 command 声明。"""
    modules: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for path in sorted((*docs_dir.glob('*.yml'), *docs_dir.glob('*.yaml'))):
        documents = yaml.safe_load(path.read_text(encoding='utf-8')) or []
        for module in documents:
            module_name = module['module_name']
            for cls in module.get('classes') or []:
                name = cls.get('class_name')
                if name:
                    modules[module_name][name] = cls
    if not modules:
        raise ValueError(f'未找到 CARLA API 文档：{docs_dir}')
    package = output_dir / 'carla'
    package.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for module_name, classes in sorted(modules.items()):
        if module_name not in ('carla', 'command'):
            raise ValueError(f'未知的 CARLA 模块：{module_name}')
        imports = ['from typing import Any']
        imports.append('from . import command' if module_name == 'carla' else 'import carla')
        lines = ['# ty: ignore', '# ruff: noqa', '', *imports, '']
        for cls in classes.values():
            lines.extend(_render_class(cls, module_name))
        output = package / ('__init__.pyi' if module_name == 'carla' else 'command.pyi')
        text = '\n'.join(lines) + '\n'
        ast.parse(text, filename=str(output))
        output.write_text(text, encoding='utf-8')
        outputs.append(output)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description='根据本地 CARLA API 文档生成类型声明')
    parser.add_argument('docs_dir', type=Path, help='CARLA PythonAPI/docs 目录')
    parser.add_argument('output_dir', type=Path, help='类型声明输出目录')
    args = parser.parse_args()
    for path in generate(args.docs_dir, args.output_dir):
        print(path)


if __name__ == '__main__':
    main()
