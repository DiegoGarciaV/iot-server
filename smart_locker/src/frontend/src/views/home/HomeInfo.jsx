import { Link } from "react-router-dom";

import styles from './HomeInfo.module.css'

const BENEFITS = [
    {
        title: "Sin cuentas ni contraseñas",
        text: "Reservas en un par de pasos y recibes un código. No necesitas registrarte.",
        icon: <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />,
    },
    {
        title: "Seguimiento en tiempo real",
        text: "Consulta el estado de tu pedido en cualquier momento desde tu teléfono.",
        icon: (
            <>
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
            </>
        ),
    },
    {
        title: "Solo tú lo abres",
        text: "Tu locker queda apartado para ti y se abre únicamente con tu código.",
        icon: (
            <>
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </>
        ),
    },
];

const STEPS = [
    {
        title: "Reserva",
        text: "Elige un locker disponible y aparta el tuyo desde esta página.",
    },
    {
        title: "Guarda",
        text: "Usa tu código para abrir el locker y deja tus cosas dentro.",
    },
    {
        title: "Recoge",
        text: "Vuelve cuando quieras, ingresa tu código y llévate tu pedido.",
    },
];

const HomeInfo = () => {

    return (
        <>
            <section className={styles.contentSection}>
                <h2 className={`${styles.heading} ${styles.sectionTitle}`}>
                    ¿Qué es Smart Locker?
                </h2>
                <p className={`${styles.bodyText} ${styles.largeText} ${styles.lead}`}>
                    Un casillero inteligente que apartas desde tu teléfono.
                    Guarda o recoge tus cosas cuando te quede bien, sin filas
                    y sin depender de nadie.
                </p>
                <ul className={styles.cardRow}>
                    {BENEFITS.map((benefit) => (
                        <li key={benefit.title} className={styles.benefit}>
                            <span className={styles.benefitIcon}>
                                <svg
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                >
                                    {benefit.icon}
                                </svg>
                            </span>
                            <div>
                                <h3 className={styles.cardTitle}>{benefit.title}</h3>
                                <p className={`${styles.bodyText} ${styles.benefitText}`}>
                                    {benefit.text}
                                </p>
                            </div>
                        </li>
                    ))}
                </ul>
            </section>

            <section className={`${styles.contentSection} ${styles.howItWorks}`}>
                <h2 className={`${styles.heading} ${styles.sectionTitle}`}>
                    ¿Cómo funciona?
                </h2>
                <ol className={styles.cardRow}>
                    {STEPS.map((step, index) => (
                        <li key={step.title} className={styles.step}>
                            <div className={styles.stepHeader}>
                                <span className={styles.stepNumber}>{index + 1}</span>
                                <h3 className={styles.cardTitle}>{step.title}</h3>
                            </div>
                            <p className={`${styles.bodyText} ${styles.stepText}`}>
                                {step.text}
                            </p>
                        </li>
                    ))}
                </ol>
                <div className={styles.callToAction}>
                    <p className={`${styles.largeText} ${styles.callToActionText}`}>
                        Reserva ahora y recibe tu código al instante.
                    </p>
                    <Link to="/reserve" className={styles.button}>
                        Reservar un locker
                    </Link>
                </div>
            </section>
        </>
    )
}

export default HomeInfo;
