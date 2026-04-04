import json
import logging
import os
import re
from typing import Dict, Optional

import yaml
from openai import OpenAI

logger = logging.getLogger(__name__)

FALLBACK_CATEGORY = "Spam / irrelevante"
FALLBACK_PRIORITY = "baja"
FALLBACK_COLOR = "gray"

# ---------------------------------------------------------------------------
# System prompt — defines the model's persona and strict output rules
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
Eres un clasificador experto de correos electrónicos para agencias inmobiliarias.
Tienes 15 años de experiencia en el sector y conoces perfectamente las urgencias del negocio.

REGLAS ABSOLUTAS:
1. Responde ÚNICAMENTE con un objeto JSON válido. Cero texto fuera del JSON.
2. El campo "category" debe coincidir EXACTAMENTE con uno de los nombres de categoría proporcionados.
3. Razona siempre en el campo "reasoning" ANTES de decidir la categoría (esto mejora tu precisión).
4. El campo "summary" debe ser 1-2 frases en español, útiles y concretas para el agente inmobiliario.
5. "Consulta general" es SOLO para clientes con dudas reales sobre propiedades o servicios inmobiliarios.
   Todo lo demás (correos que no traten de propiedades, alquiler, compra, venta o hipotecas) va a "Spam / irrelevante".
6. Nunca inventes categorías.
7. El campo "lead_score" valora la calidad del lead del 0 al 10:
   - 9-10: oferta de compra con cifra concreta o alta intención de cerrar operación
   - 7-8: fuerte interés comprador, solicitud de visita con intención clara de compra
   - 5-6: solicitud de visita, consulta de precio con interés real
   - 3-4: consulta general, interés exploratorio inicial
   - 1-2: documentación/trámites de operación ya en curso (no es nuevo lead)
   - 0: spam, irrelevante, notificaciones automáticas

FORMATO DE RESPUESTA (siempre este esquema exacto):
{"reasoning": "<tu razonamiento paso a paso>", "category": "<nombre exacto>", "summary": "<resumen útil>", "lead_score": <0-10>}
"""

THREAD_SUMMARY_PROMPT = """\
Eres un asistente para agencias inmobiliarias. Tu tarea es resumir el historial completo de una conversación por email.

REGLAS:
1. Responde ÚNICAMENTE con el resumen, en texto plano. Sin encabezados, sin listas, sin comillas.
2. Máximo 3 frases en español.
3. Indica: de qué trata la conversación, qué ha ocurrido hasta ahora y si hay algo pendiente.
4. Sé concreto: menciona cifras, fechas o propiedades si son relevantes.
"""

DRAFT_SYSTEM_PROMPT = """\
Eres un agente inmobiliario profesional. Tu tarea es redactar respuestas de correo electrónico
profesionales, concisas y efectivas en nombre de la agencia.

REGLAS:
1. Responde ÚNICAMENTE con el texto de la respuesta. Sin explicaciones, sin comillas, sin formato adicional.
2. Sé conciso: 2-3 párrafos máximo.
3. Tono profesional pero cercano, en español.
4. Responde directamente a lo que pide el cliente.
5. Propón siempre un paso siguiente concreto cuando sea apropiado.
6. NO inventes datos específicos de propiedades (precios exactos, direcciones concretas).
7. NO incluyas asunto, firma ni saludo inicial — eso lo añade el agente.
"""

# ---------------------------------------------------------------------------
# Few-shot examples — cover all categories + edge cases + ambiguous cases
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES = [
    # --- Oferta de compra ---
    {
        "sender": "Carlos Méndez <carlos.mendez@gmail.com>",
        "subject": "Oferta por el piso de Calle Mayor 14",
        "body": "Buenas tardes, tras visitar el piso el martes, mi familia y yo queremos hacer una oferta formal de 285.000€. Estamos listos para firmar arras esta semana si hay acuerdo. Por favor, comuníquese con nosotros a la mayor brevedad. Gracias.",
        "output": {
            "reasoning": "El remitente menciona explícitamente una cifra económica (285.000€), el deseo de 'hacer una oferta formal' y la disposición a firmar arras. Esto es inequívocamente una oferta de compra, la acción comercial más urgente para la agencia.",
            "category": "Oferta de compra",
            "summary": "Carlos Méndez ofrece 285.000€ por el piso de Calle Mayor 14 y está dispuesto a firmar arras esta semana. Requiere respuesta urgente.",
            "lead_score": 10
        }
    },
    # --- Solicitud de visita ---
    {
        "sender": "Laura García <laura.g@hotmail.com>",
        "subject": "Consulta sobre el apartamento ref. 4821",
        "body": "Hola, he visto su anuncio en Idealista y me gustaría concertar una visita para ver el apartamento de 3 habitaciones en el centro. ¿Tendría disponibilidad este fin de semana, preferiblemente el sábado por la mañana? Muchas gracias.",
        "output": {
            "reasoning": "La remitente solicita explícitamente 'concertar una visita' y propone una fecha concreta. Aunque menciona el anuncio de Idealista (podría confundirse con consulta general), el objetivo principal del correo es coordinar una visita presencial.",
            "category": "Solicitud de visita",
            "summary": "Laura García quiere visitar el apartamento ref. 4821 el sábado por la mañana. Hay que confirmar disponibilidad.",
            "lead_score": 7
        }
    },
    # --- Consulta de precio ---
    {
        "sender": "Javier Romero <jromero_89@yahoo.es>",
        "subject": "Precio del chalet en Urbanización Los Pinos",
        "body": "Buenas, ¿cuál es el precio final del chalet de 4 habitaciones que tienen en la Urbanización Los Pinos? ¿Tiene garaje incluido? ¿Hay posibilidad de negociar el precio? Gracias.",
        "output": {
            "reasoning": "El remitente pregunta por el precio y condiciones de negociación pero no realiza ninguna oferta concreta ni solicita visita. Es una fase exploratoria de precio, no una oferta. No hay señales de urgencia.",
            "category": "Consulta de precio",
            "summary": "Javier Romero pregunta por el precio del chalet en Los Pinos, si incluye garaje y margen de negociación.",
            "lead_score": 5
        }
    },
    # --- Documentación / trámites ---
    {
        "sender": "Notaría Pérez y Asociados <notaria@perezasociados.com>",
        "subject": "Documentación pendiente escritura compraventa – Exp. 2024/1847",
        "body": "Estimados señores, les escribimos para informarles que la firma de escritura de compraventa del inmueble del expediente 2024/1847 está prevista para el próximo día 15. Necesitamos que nos hagan llegar antes del día 12 la copia del NIF del vendedor y el certificado de deuda pendiente del préstamo hipotecario.",
        "output": {
            "reasoning": "El correo proviene de una notaría y hace referencia a documentación necesaria para una escritura de compraventa con fecha límite. Aunque tiene urgencia implícita (plazo del día 12), se clasifica como documentación/trámites ya que es un proceso administrativo-legal en curso.",
            "category": "Documentación / trámites",
            "summary": "La Notaría Pérez solicita NIF del vendedor y certificado de deuda antes del día 12 para la firma del expediente 2024/1847 el día 15.",
            "lead_score": 2
        }
    },
    # --- Consulta general ---
    {
        "sender": "Ana Belén Ruiz <anabelen.ruiz@gmail.com>",
        "subject": "Información sobre alquileres en la zona norte",
        "body": "Buenos días, estamos buscando un piso de alquiler de 2 habitaciones en la zona norte de la ciudad, con presupuesto de unos 900€/mes. ¿Tienen algo disponible? También nos interesaría saber si gestionan alquileres con opción a compra. Gracias.",
        "output": {
            "reasoning": "La remitente hace preguntas generales sobre disponibilidad de alquileres y servicios de la agencia. No hay solicitud de visita específica, ni oferta, ni trámite pendiente. Es una consulta informativa inicial.",
            "category": "Consulta general",
            "summary": "Ana Belén busca piso de alquiler de 2 hab. en zona norte por ~900€/mes y pregunta por alquiler con opción a compra.",
            "lead_score": 4
        }
    },
    # --- Spam / irrelevante ---
    {
        "sender": "Marketing Digital Pro <info@marketingpro-ofertas.com>",
        "subject": "🚀 ¡Multiplica tus ventas con nuestra plataforma de CRM inmobiliario!",
        "body": "Estimado cliente, somos Marketing Digital Pro y le ofrecemos nuestra revolucionaria plataforma de gestión de clientes para el sector inmobiliario. ¡Consiga un 40% más de conversiones! Haga clic aquí para ver nuestra demo gratuita. Oferta válida solo hasta el 31 de este mes.",
        "output": {
            "reasoning": "El remitente es una empresa externa que ofrece servicios de marketing/CRM. No hay ninguna relación con una operación inmobiliaria real. El tono y estructura son claramente publicitarios. Se clasifica como spam.",
            "category": "Spam / irrelevante",
            "summary": "Email publicitario de una empresa de marketing digital ofreciendo un CRM inmobiliario. No requiere acción.",
            "lead_score": 0
        }
    },
    # --- Spam: notificación automática de plataforma ---
    {
        "sender": "noreply@fotocasa.es",
        "subject": "Tu anuncio en Fotocasa ha recibido 3 nuevas visitas",
        "body": "Tu anuncio ref. 2847 ha recibido 3 visitas esta semana. Mejora tu visibilidad con nuestros planes Premium. Accede a tu panel de control para ver las estadísticas completas.",
        "output": {
            "reasoning": "Es una notificación automática de una plataforma de portales inmobiliarios. No hay ningún cliente real detrás, ni consulta, ni acción comercial posible. Aunque menciona 'visitas' y una referencia de inmueble, el remitente es noreply@ y el contenido es una notificación de sistema. Esto es correo automático irrelevante para la gestión diaria.",
            "category": "Spam / irrelevante",
            "summary": "Notificación automática de Fotocasa sobre estadísticas del anuncio. No requiere acción.",
            "lead_score": 0
        }
    },
    # --- Spam: factura de proveedor no inmobiliario ---
    {
        "sender": "facturacion@vodafone.es",
        "subject": "Tu factura de Vodafone de marzo está disponible",
        "body": "Estimado cliente, te informamos de que tu factura del mes de marzo ya está disponible en tu área de cliente. Importe: 45,90€. Accede a Mi Vodafone para consultarla y descargarla.",
        "output": {
            "reasoning": "Es una factura de una empresa de telecomunicaciones. No tiene ninguna relación con propiedades, clientes inmobiliarios ni operaciones de compra/venta/alquiler. Es correo administrativo de un proveedor externo, completamente ajeno al negocio inmobiliario.",
            "category": "Spam / irrelevante",
            "summary": "Factura de Vodafone de marzo por 45,90€. No tiene relación con el negocio inmobiliario.",
            "lead_score": 0
        }
    },
    # --- Spam: newsletter / suscripción ---
    {
        "sender": "newsletter@expansion.com",
        "subject": "Las noticias económicas de hoy: subida del Euríbor y mercado laboral",
        "body": "Buenos días. En el resumen económico de hoy: el Euríbor sube al 3,8%, el paro baja en 45.000 personas y el Ibex 35 abre al alza. Lee las noticias completas en Expansión.",
        "output": {
            "reasoning": "Es una newsletter de un medio económico. Aunque el Euríbor tiene relación indirecta con hipotecas, este correo no proviene de ningún cliente ni contiene ninguna acción inmobiliaria. Es una suscripción informativa genérica, no una consulta de negocio.",
            "category": "Spam / irrelevante",
            "summary": "Newsletter económica de Expansión. No proviene de un cliente ni requiere acción.",
            "lead_score": 0
        }
    },
    # --- Spam: correo personal sin relación con el negocio ---
    {
        "sender": "pepe.garcia.familiar@gmail.com",
        "subject": "Cena del viernes",
        "body": "Hola, ¿quedamos el viernes a las 21h en el restaurante de siempre? Avísame si puedes venir. Un abrazo.",
        "output": {
            "reasoning": "Es un correo personal sobre una cena. No tiene absolutamente ninguna relación con el negocio inmobiliario. No hay ningún cliente, propiedad ni trámite implicado.",
            "category": "Spam / irrelevante",
            "summary": "Correo personal sin relación con el negocio. No requiere acción.",
            "lead_score": 0
        }
    },
    # --- Lead de portal inmobiliario (NO es spam) ---
    {
        "sender": "noreply@idealista.com",
        "subject": "Nuevo contacto para tu anuncio en Idealista",
        "body": "Has recibido un mensaje de:\nNombre: María Fernández\nTeléfono: 612 345 678\nEmail: maria.f@gmail.com\n\nMensaje: Hola, estoy muy interesada en el piso de 3 habitaciones. ¿Podría concertar una visita esta semana?\n\nAnuncio: Ref. 28374 - Piso en Calle Mayor 15",
        "output": {
            "reasoning": "El correo viene de noreply@idealista.com pero contiene un mensaje real de una persona interesada en visitar un inmueble. Aunque el remitente técnico es un portal, el contenido es una solicitud de visita de un cliente real con nombre y teléfono. Los correos de portales con mensajes de clientes NO son spam; son leads.",
            "category": "Solicitud de visita",
            "summary": "María Fernández (612 345 678) solicita visitar el piso Ref. 28374 de Calle Mayor a través de Idealista.",
            "lead_score": 7
        }
    },
    # --- Caso ambiguo: podría ser visita O oferta ---
    {
        "sender": "Pedro Alonso <p.alonso.comprador@gmail.com>",
        "subject": "Re: Piso Calle Serrano 88 – muy interesados",
        "body": "Hola, somos la familia Alonso, visitamos el piso la semana pasada. Nos ha encantado y estamos muy interesados en seguir adelante. ¿Podríamos quedar esta semana para hablar de los siguientes pasos y las condiciones? Queremos movernos rápido.",
        "output": {
            "reasoning": "El correo menciona una visita previa y expresa fuerte interés en 'seguir adelante' y 'moverse rápido'. Aunque no especifica una cifra, la intención de avanzar hacia la compra y la urgencia ('movernos rápido') elevan esto más allá de una simple visita. Sin embargo, como no hay cifra ni oferta formal, la categoría más precisa es 'Oferta de compra' por la clara intención de compra manifestada. Si no existiera esa categoría, sería 'Consulta general'.",
            "category": "Oferta de compra",
            "summary": "La familia Alonso, tras visitar el piso de Serrano 88, expresa fuerte interés en comprar y quiere reunirse esta semana para hablar condiciones. Prioridad alta.",
            "lead_score": 9
        }
    },
]


def _format_few_shot_block(examples: list) -> str:
    """Format few-shot examples as a readable conversation block."""
    lines = []
    for i, ex in enumerate(examples, 1):
        lines.append(f"--- EJEMPLO {i} ---")
        lines.append(f"Remitente: {ex['sender']}")
        lines.append(f"Asunto: {ex['subject']}")
        lines.append(f"Cuerpo: {ex['body']}")
        lines.append(f"Respuesta correcta: {json.dumps(ex['output'], ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


class AIClassifier:
    def __init__(self):
        with open("config.yaml", "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        ai_cfg = self.config["ai"]
        api_key = os.getenv("NVIDIA_API_KEY", "")
        if not api_key:
            logger.warning("NVIDIA_API_KEY is not set. AI classification will fail.")

        self.client = OpenAI(
            base_url=ai_cfg["base_url"],
            api_key=api_key,
        )
        self.model = ai_cfg["model"]
        self.categories = self.config["categories"]
        self.business_name = self.config["business"]["name"]

        self._cat_meta: Dict[str, Dict] = {
            cat["name"]: {"priority": cat["priority"], "color": cat["color"]}
            for cat in self.categories
        }

        # Pre-build static parts of the prompt (don't recompute on every call)
        self._few_shot_block = _format_few_shot_block(FEW_SHOT_EXAMPLES)
        self._categories_block = self._build_categories_block()

    def _build_categories_block(self) -> str:
        lines = []
        for cat in self.categories:
            lines.append(
                f'  • "{cat["name"]}" — {cat["description"]} → prioridad: {cat["priority"]}'
            )
        return "\n".join(lines)

    def _build_prompt(self, subject: str, body: str, sender: str) -> str:
        """
        Build the full classification prompt using:
        - Role context
        - Category definitions
        - Disambiguation rules
        - Urgency signals
        - Few-shot examples
        - Chain-of-thought instruction
        """
        urgency_signals = (
            "palabras como 'urgente', 'cuanto antes', 'hoy', 'mañana', 'esta semana', "
            "'firma', 'arras', 'notaría', 'plazo', 'caducidad', 'inmediatamente'"
        )

        prompt = f"""Trabajas para la agencia "{self.business_name}".

════════════════════════════════════════
CATEGORÍAS DISPONIBLES
════════════════════════════════════════
{self._categories_block}

════════════════════════════════════════
REGLAS DE DESAMBIGUACIÓN
════════════════════════════════════════
1. Si hay una cifra económica de compra/venta → "Oferta de compra" (aunque no use la palabra "oferta").
2. Si pide visita Y muestra interés de compra claro → prioriza "Oferta de compra".
3. Si solo pregunta precio sin comprometerse → "Consulta de precio".
4. Si el remitente es notaría, banco, gestoría o se habla de contratos/escrituras → "Documentación / trámites".
5. Señales de urgencia que elevan la prioridad: {urgency_signals}.
6. Correos de empresas ofreciendo servicios externos → "Spam / irrelevante".
7. Antes de asignar "Consulta general", hazte esta pregunta: ¿El remitente es un cliente real o potencial preguntando sobre una propiedad concreta o servicio inmobiliario? Si la respuesta es NO → "Spam / irrelevante".
8. Van a "Spam / irrelevante": newsletters, facturas de proveedores, estadísticas de portales ("tu anuncio tuvo X visitas"), suscripciones, correos personales sin relación, ofertas de servicios externos, correos bancarios/de utilities.
   EXCEPCIÓN IMPORTANTE: si un correo viene de un portal (Idealista, Fotocasa, Airbnb…) pero contiene el mensaje de un cliente real interesado en una propiedad, NO es spam — clasifícalo según el contenido del mensaje del cliente.
9. "Consulta general" es ÚNICAMENTE para personas reales que preguntan sobre propiedades, alquiler, compra, venta o servicios de la agencia. En caso de duda entre "Consulta general" y "Spam / irrelevante", elige "Spam / irrelevante".
10. En caso de duda entre dos categorías inmobiliarias, elige la de mayor implicación comercial.

════════════════════════════════════════
EJEMPLOS DE CLASIFICACIÓN CORRECTA
════════════════════════════════════════
{self._few_shot_block}
════════════════════════════════════════
CORREO A CLASIFICAR AHORA
════════════════════════════════════════
Remitente: {sender}
Asunto: {subject}
Cuerpo:
{body[:2000]}

════════════════════════════════════════
INSTRUCCIÓN FINAL
════════════════════════════════════════
Analiza el correo paso a paso en el campo "reasoning", luego decide.
Responde SOLO con este JSON (sin texto adicional, sin bloques de código):
{{"reasoning": "<razonamiento>", "category": "<nombre exacto de la categoría>", "summary": "<1-2 frases útiles para el agente>"}}"""

        return prompt

    def classify_email(
        self, subject: str, body: str, sender: str
    ) -> Dict[str, Optional[str]]:
        """
        Classify a single email using chain-of-thought + few-shot prompting.
        Returns: category, priority, color, summary.
        Falls back to 'Consulta general' on any error.
        """
        prompt = self._build_prompt(subject, body, sender)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,   # Low temperature → consistent, deterministic output
                max_tokens=512,    # More room for reasoning field
            )

            raw = response.choices[0].message.content.strip()
            logger.debug("LLM raw response: %s", raw)

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = re.sub(r"```[a-z]*\n?", "", raw).strip().rstrip("```").strip()

            # Extract first JSON object in case the model adds trailing text
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                raw = json_match.group(0)

            result = json.loads(raw)

            category = result.get("category", FALLBACK_CATEGORY)
            summary = result.get("summary", "")
            reasoning = result.get("reasoning", "")
            lead_score = result.get("lead_score")

            if reasoning:
                logger.debug("LLM reasoning: %s", reasoning)

            # Validate category — fuzzy match if needed
            if category not in self._cat_meta:
                # Try case-insensitive match
                normalized = {k.lower(): k for k in self._cat_meta}
                matched = normalized.get(category.lower())
                if matched:
                    category = matched
                else:
                    logger.warning("LLM returned unknown category '%s', falling back.", category)
                    category = FALLBACK_CATEGORY

            # Clamp lead_score to 0-10
            if lead_score is not None:
                try:
                    lead_score = max(0, min(10, int(lead_score)))
                except (ValueError, TypeError):
                    lead_score = None

            meta = self._cat_meta.get(category, {"priority": FALLBACK_PRIORITY, "color": FALLBACK_COLOR})

            return {
                "category": category,
                "priority": meta["priority"],
                "color": meta["color"],
                "summary": summary,
                "lead_score": lead_score,
            }

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse LLM JSON response: %s | raw: %s", exc, raw if 'raw' in dir() else "")
        except Exception as exc:
            logger.error("LLM classification error: %s", exc)

        # Fallback
        meta = self._cat_meta.get(FALLBACK_CATEGORY, {"priority": FALLBACK_PRIORITY, "color": FALLBACK_COLOR})
        return {
            "category": FALLBACK_CATEGORY,
            "priority": meta["priority"],
            "color": meta["color"],
            "summary": "No se pudo clasificar automáticamente.",
            "lead_score": None,
        }

    def summarize_thread(self, emails: list) -> str:
        """Generate a concise summary of an email thread conversation."""
        lines = []
        for e in sorted(emails, key=lambda x: x.get("received_at") or ""):
            date = (e.get("received_at") or "")[:10]
            lines.append(f"[{date}] De: {e.get('sender', '')} — Asunto: {e.get('subject', '')}")
            preview = (e.get("body_preview") or "").strip()
            if preview:
                lines.append(preview[:300])
            lines.append("")

        prompt = f"Resume este hilo de conversación de email:\n\n{''.join(lines)[:3000]}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": THREAD_SUMMARY_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()

    def draft_reply(self, subject: str, body: str, sender: str, category: str) -> str:
        """Generate a professional email reply draft using AI."""
        prompt = f"""Agencia: {self.business_name}

Correo recibido:
De: {sender}
Asunto: {subject}
Categoría: {category}
Contenido:
{body[:1500]}

Redacta una respuesta profesional a este correo."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
