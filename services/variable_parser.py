"""
Variable Parser for prompt templates.
Replaces @variable patterns with actual data.
"""

import re
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger


class VariableParser:
    """
    Parses and replaces variables in prompt templates.
    
    Variables use the format @category.field, e.g.:
    - @user.name
    - @mac.sun
    - @system.date
    """
    
    # Pattern to match @category.field variables
    VARIABLE_PATTERN = re.compile(r'@(\w+)\.(\w+)')
    
    def __init__(self):
        self._data_cache: Dict[str, Dict[str, Any]] = {}
    
    def set_context(
        self,
        user_data: Optional[Dict[str, Any]] = None,
        mac_data: Optional[Dict[str, Any]] = None,
        test_data: Optional[Dict[str, Any]] = None,
        custom_data: Optional[Dict[str, Any]] = None
    ):
        """Set the data context for variable replacement."""
        self._data_cache = {
            "user": user_data or {},
            "mac": mac_data or {},
            "test": test_data or {},
            "custom": custom_data or {},
            "system": self._get_system_data()
        }
    
    def _get_system_data(self) -> Dict[str, Any]:
        """Generate system variables."""
        now = datetime.now()
        return {
            "date": now.strftime("%d/%m/%Y"),
            "date_full": now.strftime("%d de %B de %Y"),
            "time": now.strftime("%H:%M"),
            "datetime": now.strftime("%d/%m/%Y %H:%M"),
            "weekday": now.strftime("%A"),
            "month": now.strftime("%B"),
            "year": str(now.year)
        }
    
    def _get_value(self, category: str, field: str) -> str:
        """Get value for a variable, with fallback mappings."""
        import json
        
        data = self._data_cache.get(category, {})
        
        # Tratamento especial para .full (retorna JSON completo da categoria)
        if field == "full":
            if data:
                return json.dumps(data, ensure_ascii=False, default=str)
            else:
                logger.warning(f"Variable @{category}.{field} - data is empty")
                return "{}"
        
        # Direct field lookup
        value = data.get(field)
        if value is not None:
            # Se for dict ou list, retornar como JSON
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)
            return str(value)
        
        # Field mappings for common variations
        field_mappings = {
            "mac": {
                "sun": ["sol_signo", "sol"],
                "sun_full": ["sol"],
                "moon": ["lua_signo", "lua"],
                "moon_full": ["lua"],
                "ascendant": ["ascendente_signo", "asc_signo", "ascendente"],
                "midheaven": ["mc_signo", "meio_ceu_signo", "mc"],
                "mercury": ["mercurio_signo", "mercurio"],
                "venus": ["venus_signo", "venus"],
                "mars": ["marte_signo", "marte"],
                "jupiter": ["jupiter_signo", "jupiter"],
                "saturn": ["saturno_signo", "saturno"],
                "birth_date": ["data_nascimento"],
                "birth_city": ["cidade"],
                "birth_time": ["hora_nascimento"]
            },
            "user": {
                "name": ["nome", "full_name", "display_name"],
                "first_name": ["primeiro_nome"],
                "email": ["email"],
                "plan": ["plano", "subscription_plan"]
            }
        }
        
        # Try mapped fields
        mappings = field_mappings.get(category, {}).get(field, [])
        for mapped_field in mappings:
            value = data.get(mapped_field)
            if value is not None:
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False, default=str)
                return str(value)
        
        # Return placeholder if not found
        logger.warning(f"Variable @{category}.{field} not found in context")
        return f"[@{category}.{field}]"
    
    def parse(self, template: str) -> str:
        """
        Parse a template and replace all variables.
        
        Args:
            template: The prompt template with @variables
            
        Returns:
            Template with variables replaced by actual values
        """
        def replacer(match):
            category = match.group(1)
            field = match.group(2)
            return self._get_value(category, field)
        
        return self.VARIABLE_PATTERN.sub(replacer, template)
    
    def extract_variables(self, template: str) -> list:
        """
        Extract all variables from a template.
        
        Returns:
            List of tuples (category, field) for each variable found
        """
        matches = self.VARIABLE_PATTERN.findall(template)
        return [(cat, field) for cat, field in matches]
    
    def validate_template(self, template: str) -> Dict[str, Any]:
        """
        Validate a template and check for issues.
        
        Returns:
            Dict with 'valid', 'variables', 'warnings' keys
        """
        variables = self.extract_variables(template)
        warnings = []
        
        # Check for common issues
        known_categories = {"user", "mac", "test", "system", "custom"}
        for cat, field in variables:
            if cat not in known_categories:
                warnings.append(f"Unknown category: @{cat}.{field}")
        
        return {
            "valid": len(warnings) == 0,
            "variables": [f"@{cat}.{field}" for cat, field in variables],
            "warnings": warnings
        }


# Singleton instance
_parser_instance: Optional[VariableParser] = None


def get_variable_parser() -> VariableParser:
    """Get singleton parser instance."""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = VariableParser()
    return _parser_instance
