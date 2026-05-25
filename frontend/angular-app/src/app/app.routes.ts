import { Routes } from '@angular/router';
import { Login } from './paginas/login/login';
import { Registro } from './paginas/registro/registro';
import { Dashboard } from './paginas/dashboard/dashboard';
import { AnalisisProyecto } from './paginas/analisis-proyecto/analisis-proyecto';
import { HistorialProyectos } from './paginas/historial-proyectos/historial-proyectos';
import { VerDocumentacion } from './paginas/ver-documentacion/ver-documentacion';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full',
  },
  {
    path: 'login',
    component: Login,
  },
  {
    path: 'registro',
    component: Registro,
  },
  {
    path: 'dashboard',
    component: Dashboard,
  },
  {
    path: 'analisis-proyecto',
    component: AnalisisProyecto,
  },
  {
    path: 'historial-proyectos',
    component: HistorialProyectos,
  },
  {
    path: 'documentacion/:id',
    component: VerDocumentacion,
  },
];