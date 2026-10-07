import { useEffect, useRef, useState } from "react";
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

import Header from "./views/header/Header";
import Footer from "./views/footer/Footer";
import Home from "./views/home/Home";

const SmartLockerDashboard = () => {

    return (
        <Router>
            <Header></Header>
            <Routes>
                <Route 
                    path="/" 
                    element={<Home />} 
                />
            </Routes>
            <Footer></Footer>
        </Router>
    )
}

export default SmartLockerDashboard;