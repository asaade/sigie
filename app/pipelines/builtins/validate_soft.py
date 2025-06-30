# app/pipelines/builtins/validate_soft.py

from __future__ import annotations
import logging # Necesario para logging.info/debug/warning
from typing import List # Necesario para List[Item]

from ..registry import register
from app.schemas.models import Item
from app.schemas.item_schemas import ReportEntrySchema # Necesario para crear instancias de ReportEntrySchema
# Asumo que soft_validate es el nombre de la función que contiene la lógica de soft.py
# (No tengo acceso directo para verificar si es el nombre correcto, pero es la convención)
from app.validators.soft import soft_validate
from app.pipelines.abstractions import BaseStage # CRÍTICO: Importamos BaseStage

# Importar solo las helpers que NO son métodos de BaseStage y que se usan directamente aquí.
from ..utils.stage_helpers import (
    skip_if_terminal_error,
    handle_missing_payload,
)


logger = logging.getLogger(__name__) # Definir logger para este módulo

@register("validate_soft")
class ValidateSoftStage(BaseStage): # CRÍTICO: Convertido a clase que hereda de BaseStage
    """
    Etapa de validación "suave" (estilística) de los ítems.
    Implementada como una clase Stage.
    """

    async def execute(self, items: List[Item]) -> List[Item]:
        """
        Punto de entrada principal de la etapa de validación suave.
        Aplica reglas de estilo y formato localmente, generando advertencias.
        """
        self.logger.info(f"Starting soft validation for {len(items)} items.")

        for item in items: # Iteramos sobre todos los ítems
            # skip_if_terminal_error ya añade la auditoría y gestiona el salto.
            # Esta comprobación es necesaria para las etapas que no heredan de LLMStage.
            if skip_if_terminal_error(item, self.stage_name):
                continue

            # handle_missing_payload ya añade la auditoría y marca el ítem como fallo.
            # Esta comprobación es necesaria para las etapas que no heredan de LLMStage.
            if not item.payload:
                handle_missing_payload( # Llamada directa a la helper
                    item, self.stage_name, "E952_NO_PAYLOAD", "El ítem no tiene un payload para validar el estilo.",
                    f"{self.stage_name}.fail.no_payload", "Saltado: no hay payload de ítem para validar el estilo."
                )
                continue

            item_dict_payload = item.payload.model_dump()

            # La lógica de validación real está en app/validators/soft.py
            soft_findings_raw = soft_validate(item_dict_payload)

            current_findings: List[ReportEntrySchema] = []
            for finding in soft_findings_raw:
                # CORRECCIÓN: Usar "code" en lugar de "warning_code" y obtener "severity" y "fix_hint"
                current_findings.append(
                    ReportEntrySchema(
                        code=finding.get("code", "UNKNOWN_SOFT_FINDING"), # Usar "code"
                        message=finding.get("message", "Advertencia de estilo no especificada."),
                        field=finding.get("field"),
                        severity=finding.get("severity", "warning"), # Obtener severity real
                        fix_hint=finding.get("fix_hint", None) # Obtener fix_hint
                    )
                )

            # LÓGICA DE ACTUALIZACIÓN ALINEADA CON BaseStage
            if current_findings:
                item.findings.extend(current_findings)
                summary = f"Soft validation completed. {len(current_findings)} warnings/errors issued."
                # La validación suave NO cambia el estado a "fallido" si solo hay advertencias.
                # Se marca como éxito para indicar que pasó esta etapa, y las advertencias se acumulan.
                self._set_status(item, "success", summary) # Usar _set_status de BaseStage
                self.logger.info(f"Item {item.temp_id} received {len(current_findings)} style warnings/errors.")
            else:
                summary = "Soft validation completed. No issues found."
                self._set_status(item, "success", summary) # Usar _set_status de BaseStage
                self.logger.info(f"Item {item.temp_id} passed soft validation with no warnings.")

        self.logger.info("Soft validation stage completed for all items.")
        return items
