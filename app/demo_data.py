"""
demo_data.py — Load / unload realistic sample emails for demo mode.

Activated via config.yaml:
    demo:
      enabled: true
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Email

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample emails — cover all categories, portals, scores and states
# ---------------------------------------------------------------------------
def _emails():
    """Build demo email list with dates relative to now."""
    now = datetime.utcnow()
    def ago(**kw): return now - timedelta(**kw)

    return [
        # 1 — Oferta de compra urgente (directo)
        dict(
            gmail_id="demo_001",
            sender="Carlos Méndez",
            sender_email="carlos.mendez@gmail.com",
            subject="Oferta formal — Piso Avda. Constitución 45",
            body_preview=(
                "Estimados, tras visitar el piso el martes con mi familia quiero hacer "
                "una oferta formal de 287.000€. Estamos dispuestos a firmar arras esta "
                "semana si hay acuerdo. Llámenos a la mayor brevedad posible. Gracias."
            ),
            category="Oferta de compra", priority="urgente", color="red",
            summary="Carlos Méndez ofrece 287.000 € por Avda. Constitución 45 y puede firmar arras esta semana. Respuesta urgente.",
            lead_score=10, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=False, is_replied=False, is_archived=False, received_at=ago(hours=1),
        ),
        # 2 — Lead Idealista (solicitud de visita)
        dict(
            gmail_id="demo_002",
            sender="Idealista",
            sender_email="noreply@idealista.com",
            subject="Nuevo contacto para tu anuncio — Ref. 28374",
            body_preview=(
                "Has recibido un mensaje de:\n"
                "Nombre: María Fernández\nTeléfono: 612345678\n\n"
                "Mensaje: Hola, estoy muy interesada en el piso de 3 habitaciones "
                "del centro. ¿Tiene disponibilidad para visita este sábado por la mañana?\n\n"
                "Anuncio: Ref. 28374 — Piso en Calle Mayor 15"
            ),
            category="Solicitud de visita", priority="alta", color="orange",
            summary="María Fernández (612345678) solicita visita para el piso Ref. 28374 de Calle Mayor a través de Idealista.",
            lead_score=7, lead_source="Idealista", lead_name="María Fernández",
            lead_phone="612345678", lead_property_ref="28374",
            is_read=False, is_replied=False, is_archived=False, received_at=ago(hours=2),
        ),
        # 3 — Lead Fotocasa (oferta implícita)
        dict(
            gmail_id="demo_003",
            sender="Fotocasa",
            sender_email="noreply@fotocasa.es",
            subject="Nuevo mensaje de contacto — Chalet Los Pinos",
            body_preview=(
                "Nombre: Pedro Alonso\nTeléfono: 698112233\n\n"
                "Mensaje: Visitamos el chalet la semana pasada y nos encantó. "
                "Estamos muy interesados en seguir adelante. ¿Podemos quedar "
                "esta semana para hablar de condiciones? Queremos movernos rápido.\n\n"
                "Ref. anuncio: FC-91827"
            ),
            category="Oferta de compra", priority="urgente", color="red",
            summary="Pedro Alonso (698112233) quiere avanzar en la compra del chalet Ref. FC-91827. Alta intención de compra. Contactar hoy.",
            lead_score=9, lead_source="Fotocasa", lead_name="Pedro Alonso",
            lead_phone="698112233", lead_property_ref="FC-91827",
            is_read=False, is_replied=False, is_archived=False, received_at=ago(hours=3),
        ),
        # 4 — Lead Airbnb (solicitud de reserva vacacional)
        dict(
            gmail_id="demo_004",
            sender="Airbnb",
            sender_email="automated@airbnb.com",
            subject="Nueva solicitud de reserva — Apartamento Playa Norte",
            body_preview=(
                "Tienes una nueva solicitud de reserva.\n\n"
                "Huésped: Sophie Laurent\nFechas: 15 al 22 de agosto\n"
                "Huéspedes: 4 personas\n\n"
                "Mensaje: Hola, somos una familia francesa buscando apartamento "
                "en la costa para la segunda quincena de agosto. ¿Está disponible?"
            ),
            category="Solicitud de visita", priority="alta", color="orange",
            summary="Sophie Laurent solicita reserva del apartamento Playa Norte del 15 al 22 de agosto para 4 personas. Confirmar disponibilidad.",
            lead_score=6, lead_source="Airbnb", lead_name="Sophie Laurent",
            lead_phone=None, lead_property_ref=None,
            is_read=False, is_replied=False, is_archived=False, received_at=ago(hours=5),
        ),
        # 5 — Lead Habitaclia (consulta de precio)
        dict(
            gmail_id="demo_005",
            sender="Habitaclia",
            sender_email="noreply@habitaclia.com",
            subject="Nuevo mensaje sobre tu propiedad — Ref. HAB-4421",
            body_preview=(
                "Nombre: Jordi Puig\nTeléfono: 934556677\n\n"
                "Mensaje: Buenos días, ¿cuál es el precio final del piso? "
                "¿Tiene plaza de garaje incluida? ¿Hay posibilidad de negociar? Gracias."
            ),
            category="Consulta de precio", priority="media", color="yellow",
            summary="Jordi Puig (934556677) pregunta precio final, garaje y margen de negociación del piso Ref. HAB-4421 en Habitaclia.",
            lead_score=5, lead_source="Habitaclia", lead_name="Jordi Puig",
            lead_phone="934556677", lead_property_ref="HAB-4421",
            is_read=True, is_replied=False, is_archived=False, received_at=ago(hours=8),
        ),
        # 6 — Lead Pisos.com (consulta general)
        dict(
            gmail_id="demo_006",
            sender="Pisos.com",
            sender_email="noreply@pisos.com",
            subject="Interesado en tu anuncio de alquiler",
            body_preview=(
                "Nombre: Ana Belén Ruiz\n\n"
                "Mensaje: Buenas, estamos buscando piso de alquiler de 2 habitaciones "
                "en zona norte, presupuesto unos 900€/mes. ¿Tienen algo disponible? "
                "¿Gestionan alquileres con opción a compra?"
            ),
            category="Consulta general", priority="media", color="green",
            summary="Ana Belén Ruiz busca alquiler 2 hab. zona norte ~900 €/mes a través de Pisos.com. Pregunta por opción a compra.",
            lead_score=4, lead_source="Pisos.com", lead_name="Ana Belén Ruiz",
            lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=False, is_archived=False, received_at=ago(hours=12),
        ),
        # 7 — Solicitud de visita directa (ya respondida)
        dict(
            gmail_id="demo_007",
            sender="Laura García",
            sender_email="laura.g@hotmail.com",
            subject="Visita apartamento ref. 4821 — sábado mañana",
            body_preview=(
                "Hola, he visto su anuncio en Idealista y me gustaría concertar "
                "una visita para ver el apartamento de 3 habitaciones. ¿Tienen "
                "disponibilidad el sábado por la mañana? Muchas gracias."
            ),
            category="Solicitud de visita", priority="alta", color="orange",
            summary="Laura García quiere visitar el apartamento ref. 4821 el sábado por la mañana. Visita confirmada.",
            lead_score=7, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=True, is_archived=False, received_at=ago(days=1),
        ),
        # 8 — Documentación notaría (trámites)
        dict(
            gmail_id="demo_008",
            sender="Notaría Pérez y Asociados",
            sender_email="notaria@perezasociados.com",
            subject="Documentación pendiente escritura — Exp. 2024/1847",
            body_preview=(
                "Estimados, la firma de escritura del expediente 2024/1847 está "
                "prevista para el día 15. Necesitamos antes del día 12 la copia del "
                "NIF del vendedor y el certificado de deuda del préstamo hipotecario."
            ),
            category="Documentación / trámites", priority="alta", color="blue",
            summary="Notaría Pérez necesita NIF del vendedor y certificado de deuda antes del día 12 para la firma del exp. 2024/1847.",
            lead_score=2, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=False, is_archived=False, received_at=ago(days=1, hours=3),
        ),
        # 9 — Oferta de compra (segunda, para mostrar count urgente)
        dict(
            gmail_id="demo_009",
            sender="Familia Alonso",
            sender_email="p.alonso.comprador@gmail.com",
            subject="Re: Piso Calle Serrano 88 — muy interesados",
            body_preview=(
                "Hola, somos la familia Alonso, visitamos el piso la semana pasada. "
                "Nos encantó y queremos seguir adelante. ¿Podríamos quedar esta semana "
                "para hablar de los siguientes pasos? Queremos movernos rápido."
            ),
            category="Oferta de compra", priority="urgente", color="red",
            summary="La familia Alonso quiere avanzar en la compra del piso de Serrano 88. Piden reunión esta semana.",
            lead_score=9, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=False, is_replied=False, is_archived=False, received_at=ago(days=2),
        ),
        # 10 — Consulta de precio directa
        dict(
            gmail_id="demo_010",
            sender="Javier Romero",
            sender_email="jromero_89@yahoo.es",
            subject="Precio chalet Urbanización Los Pinos",
            body_preview=(
                "Buenas, ¿cuál es el precio final del chalet de 4 habitaciones en "
                "Los Pinos? ¿Tiene garaje incluido? ¿Hay posibilidad de negociar? Gracias."
            ),
            category="Consulta de precio", priority="media", color="yellow",
            summary="Javier Romero pregunta precio del chalet en Los Pinos, si incluye garaje y margen de negociación.",
            lead_score=5, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=False, is_archived=False, received_at=ago(days=2, hours=6),
        ),
        # 11 — Spam (marketing)
        dict(
            gmail_id="demo_011",
            sender="Marketing Digital Pro",
            sender_email="info@marketingpro-ofertas.com",
            subject="🚀 ¡Multiplica tus ventas con nuestro CRM inmobiliario!",
            body_preview=(
                "Estimado cliente, le ofrecemos nuestra revolucionaria plataforma de "
                "gestión para el sector inmobiliario. ¡40% más de conversiones! "
                "Haga clic aquí para ver nuestra demo gratuita."
            ),
            category="Spam / irrelevante", priority="baja", color="gray",
            summary="Email publicitario de empresa de marketing. No requiere acción.",
            lead_score=0, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=False, is_archived=False, received_at=ago(days=3),
        ),
        # 12 — Email archivado (para mostrar sección Archivados)
        dict(
            gmail_id="demo_012",
            sender="Banco Santander",
            sender_email="noreply@bancosantander.es",
            subject="Tu extracto de cuenta de marzo ya está disponible",
            body_preview="Tu extracto bancario del mes de marzo ya está disponible en tu banca online.",
            category="Spam / irrelevante", priority="baja", color="gray",
            summary="Extracto bancario de marzo. No relacionado con el negocio.",
            lead_score=0, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=False, is_archived=True, received_at=ago(days=4),
        ),
        # 13 — Consulta general
        dict(
            gmail_id="demo_013",
            sender="Roberto Sanz",
            sender_email="roberto.sanz.78@gmail.com",
            subject="Información sobre vuestros servicios",
            body_preview=(
                "Buenas tardes, me pongo en contacto porque estoy pensando en poner "
                "mi piso a la venta y me gustaría saber cómo trabajáis, qué comisiones "
                "cobráis y cuánto tiempo tardáis en vender. Gracias."
            ),
            category="Consulta general", priority="media", color="green",
            summary="Roberto Sanz quiere vender su piso y pregunta por comisiones y plazos del servicio.",
            lead_score=4, lead_source=None, lead_name=None, lead_phone=None, lead_property_ref=None,
            is_read=True, is_replied=False, is_archived=False, received_at=ago(days=3, hours=2),
        ),
    ]


def load_demo_data() -> None:
    """Insert demo emails if they don't already exist."""
    from app.models import Contact
    db = SessionLocal()
    try:
        inserted = 0
        for data in _emails():
            exists = db.query(Email).filter(Email.gmail_id == data["gmail_id"]).first()
            if exists:
                continue
            email = Email(**data, thread_id=None, raw_labels=None, is_demo=True)
            db.add(email)
            try:
                db.commit()
                inserted += 1
                # Upsert contact so CRM is populated in demo mode
                if email.sender_email:
                    contact = db.query(Contact).filter(Contact.email == email.sender_email).first()
                    if contact is None:
                        db.add(Contact(
                            email=email.sender_email,
                            name=email.lead_name or email.sender,
                            phone=email.lead_phone,
                            lead_source=email.lead_source,
                        ))
                        db.commit()
            except IntegrityError:
                db.rollback()
        if inserted:
            logger.info("Demo mode: inserted %d sample emails.", inserted)
        else:
            logger.info("Demo mode: sample emails already present.")
    finally:
        db.close()


def unload_demo_data() -> None:
    """Delete all demo emails from the database."""
    db = SessionLocal()
    try:
        deleted = db.query(Email).filter(Email.is_demo == True).delete()  # noqa: E712
        db.commit()
        if deleted:
            logger.info("Demo mode disabled: removed %d demo emails.", deleted)
    finally:
        db.close()
