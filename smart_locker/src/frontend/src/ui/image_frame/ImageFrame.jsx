import { useEffect, useRef, useState } from "react";

import styles from './ImageFrame.module.css'

const ImageFrame = ({ children, filter=true }) => {

    return (
        <div className={styles.imageFrame}>
            <div 
                className={`${styles.imgFilter} ${filter ? styles.bluredFilter : ""}`}
                style={{background: `url('${children}')`}}
            >
                <img src={children} alt=""/>
            </div>
        </div>
    )
}

export default ImageFrame;