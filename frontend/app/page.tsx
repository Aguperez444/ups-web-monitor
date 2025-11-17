"use client";

import { useEffect, useState } from "react";

interface UpsSummary {
    status: string;
    load_percent: number | null;
    input_voltage: number | null;
    output_voltage: number | null;
    battery_charge: number | null;
    battery_voltage: number | null;
    output_frequency: number | null;
}

export default function Home() {
    const [data, setData] = useState<UpsSummary | null>(null);
    const [loading, setLoading] = useState(true);

    async function fetchData() {
        try {
            const res = await fetch("http://localhost:5601/ups/summary");
            const json = await res.json();
            setData(json);
            setLoading(false);
        } catch (err) {
            console.error(err);
        }
    }

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 2000);
        return () => clearInterval(interval);
    }, []);

    if (loading || !data) {
        return (
            <main className="flex h-screen items-center justify-center">
                <p className="text-xl text-gray-700">Cargando datos del UPS…</p>
            </main>
        );
    }

    return (
        <main className="p-8 max-w-3xl mx-auto">
            <h1 className="text-3xl font-bold mb-6">UPS Dashboard</h1>

            <div className="grid grid-cols-2 gap-4">
                <Card title="Estado" value={data.status} />
                <Card title="Carga (%)" value={data.load_percent} />
                <Card title="Voltaje Entrada" value={data.input_voltage + " V"} />
                <Card title="Voltaje Salida" value={data.output_voltage + " V"} />
                <Card title="Nivel Batería (%)" value={data.battery_charge} />
                <Card title="Voltaje Batería" value={data.battery_voltage + " V"} />
                <Card title="Frecuencia" value={data.output_frequency + " Hz"} />
            </div>
        </main>
    );
}

function Card({ title, value }: { title: string; value: any }) {
    return (
        <div className="bg-white shadow rounded p-4 border">
            <p className="text-sm text-gray-600">{title}</p>
            <p className="text-2xl font-semibold">{value}</p>
        </div>
    );
}
