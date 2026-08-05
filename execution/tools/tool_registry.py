from typing import Type, Callable, List
from pydantic import BaseModel

class Tool:
    """ Описание одного Tool """
    def __init__(
        self,
        name: str,
        description: str,
        output_schema: Type[BaseModel],
        handler: Callable = None
    ):
        self.name = name
        self.description = description
        self.output_schema = output_schema
        self.handler = handler
        
    def to_anthropic_format(self) -> dict:
        """Превращает Pydantic модель в JSON Schema для Anthropic."""
        schema = self.output_schema.model_json_schema()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
                "additionalProperties": False,
            }
        }
class ToolRegistry:
    """Реестр всех tools."""
    def __init__(self):
            self.tools = {}

    def add(self, tool: Tool):
        """Добавить tool."""
        self.tools[tool.name] = tool

    def get(self, name: str):
        """Получить tool по имени."""
        return self.tools.get(name)
        
    def get_all(self) -> List[Tool]:
        """Получить все tools."""
        return list(self.tools.values())

    def to_anthropic_format(self) -> List[dict]:
        """Вернуть все tools в формате для Anthropic API."""
    
        return [tool.to_anthropic_format() for tool in self.get_all()]