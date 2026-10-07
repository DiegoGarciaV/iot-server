import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import ImageFrame from "../../ui/image_frame/ImageFrame";

import styles from './Home.module.css'

const ActionOption = ({children, url, img, description}) => {

    return (
        <Link to={url} className={styles.actionOption}>
            <div className={styles.imageContainer}>
                <ImageFrame filter={false}>{img}</ImageFrame>
            </div>
            <h2>{children}</h2>
            <p className={styles.description}>{description}</p>
        </Link>
    )
}

export default ActionOption;