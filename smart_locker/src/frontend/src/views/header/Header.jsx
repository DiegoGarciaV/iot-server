import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import styles from './Header.module.css'

const Header = () => {

    return (
        <nav className={styles.spaHeader}>
            <Link to="/" className={styles.headerTitle}>
                Smart Locker
            </Link>
            <div className={styles.headerLinks}>
                <Link to="/reserve">Reservar</Link>
                <Link to="/check-order">Consultar pedido</Link>
            </div>
        </nav>
    )
}

export default Header;