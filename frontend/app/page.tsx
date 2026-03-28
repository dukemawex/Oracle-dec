import ForecastCards from '../components/ForecastCards';
import CalibrationChart from '../components/CalibrationChart';
import BrierPanel from '../components/BrierPanel';
import ExtremizationPanel from '../components/ExtremizationPanel';

export const revalidate = 30;

export default function DashboardPage(): JSX.Element {
  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">OracleDeck</h1>
        <p className="text-slate-400">Live superforecaster dashboard (ISR 30s + SWR 30s polling)</p>
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        <BrierPanel />
      </div>

      <div>
        <h2 className="mb-3 text-xl font-semibold">Calibration</h2>
        <CalibrationChart />
      </div>

      <div>
        <h2 className="mb-3 text-xl font-semibold">Extremization</h2>
        <ExtremizationPanel />
      </div>

      <div>
        <h2 className="mb-3 text-xl font-semibold">Forecasts</h2>
        <ForecastCards />
      </div>
    </section>
  );
}
