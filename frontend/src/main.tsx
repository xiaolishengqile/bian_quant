import { createRoot } from 'react-dom/client';
import App from './App';
import './styles/base.css';
import './styles/dashboard.css';
import './styles/forms.css';
import './styles/responsive.css';

createRoot(document.getElementById('root')!).render(<App />);
