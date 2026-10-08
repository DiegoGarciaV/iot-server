import { useEffect, useRef, useState } from "react";
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

import Header from "./views/header/Header";
import Footer from "./views/footer/Footer";
import Home from "./views/home/Home";

const SmartLockerDashboard = () => {

    return (
        <Router>
            <Header></Header>
            <div className="spa-container">
                <Routes>
                    <Route 
                        path="/" 
                        element={<Home />} 
                    />
                </Routes>
            </div>
            <Footer></Footer>
        </Router>
    )
}

export default SmartLockerDashboard;