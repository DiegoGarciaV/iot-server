import { useEffect, useRef, useState } from "react";
import Cover from "../cover/Cover";
import ActionOption from "./ActionOption";

import styles from './Home.module.css'

const Home = () => {

    return (
        <div className={styles.homeContainer}>
            <Cover></Cover>
            <h1>¿Qué quieres hacer hoy?</h1>
            <p className={styles.subtitle}>
                Reserva un locker o revisa el estado de tu pedido.
            </p>
            <div className={styles.optionsContainer}>
                <ActionOption
                    url={"/reserve"}
                    img={"/images/reserve.png"}
                    description={"Aparta un locker en un par de pasos."}
                >
                    Reservar un locker
                </ActionOption>
                <ActionOption
                    url={"/check-order"}
                    img={"/images/check-order.png"}
                    description={"Revisa el estado de tu pedido con tu código."}
                >
                    Consultar mi pedido
                </ActionOption>
            </div>
        </div>
    )
}

export default Home;