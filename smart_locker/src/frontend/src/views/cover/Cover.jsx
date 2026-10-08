import { useEffect, useRef, useState } from "react";
import styles from './Cover.module.css'

const Cover = () => {

    return (
        <div className={styles.coverContainer}>
            <h1>Smart Locker</h1>
            <div className={styles.accent}></div>
            <p className={styles.tagline}>Reserva, guarda y recoge</p>
        </div>
    )
}

export default Cover;
