# app/pipelines/builtins/validate_soft.py
import logging
from typing import List

from app.schemas.item_schemas import ReportEntrySchema
from app.schemas.models import Item
from app.validators.soft import soft_validate # Importa la función de validación
from app.pipelines.abstractions import BaseStage
from app.pipelines.registry import register

logger = logging.getLogger(__name__)

@register("validate_soft")
class ValidateSoftStage(BaseStage):
    """
    Etapa de validación "suave" que aplica reglas de estilo, lenguaje y formato no estrictas.
    Estas validaciones son susceptibles de refinamiento por LLM.
    """
    async def execute(self, items: List[Item]) -> List[Item]:
        logger.info(f"Iniciando etapa de validación suave para {len(items)} ítems.")
        updated_items = []

        for item in items:
            # Asegurarse de que el payload sea un dict compatible con soft_validate
            # Pydantic v2 .model_dump(mode='json') es preferible a .dict() para asegurar la serialización correcta
            item_dict_payload = item.payload.model_dump(mode='json') # MODIFICADO: Usar model_dump
            soft_findings_raw = soft_validate(item_dict_payload) # Invoca la lógica de soft.py

            # Filtrar solo los findings que no existen ya para evitar duplicados
            existing_finding_codes = {f.code for f in item.findings}
            current_findings: List[ReportEntrySchema] = list(item.findings)

            for finding in soft_findings_raw:
                if finding.get("code") not in existing_finding_codes:
                    current_findings.append(
                        ReportEntrySchema(
                            code=finding.get("code", "UNKNOWN_SOFT_FINDING"),
                            message=finding.get("message", "Advertencia de estilo no especificada."),
                            field=finding.get("field"),
                            severity=finding["severity"], # Correcto: Toma la severidad del finding que viene de get_centralized_error_info en soft.py
                            fix_hint=finding.get("fix_hint", None) # Correcto: Toma el fix_hint del finding que viene de get_centralized_error_info
                        )
                    )
            item.findings = current_findings
            updated_items.append(item)

        logger.info(f"Etapa de validación suave completada. {len(updated_items)} ítems procesados.")
        return updated_items
