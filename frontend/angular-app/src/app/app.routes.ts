import { Routes } from '@angular/router';
import { Login } from './paginas/login/login';
import { Registro } from './paginas/registro/registro';
import { Dashboard } from './paginas/dashboard/dashboard';
import { AnalisisProyecto } from './paginas/analisis-proyecto/analisis-proyecto';
import { HistorialProyectos } from './paginas/historial-proyectos/historial-proyectos';
import { VerDocumentacion } from './paginas/ver-documentacion/ver-documentacion';
import { authGuard } from './guards/auth.guard';
import { guestGuard } from './guards/guest.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full',
  },
  {
    path: 'login',
    component: Login,
    canActivate: [guestGuard],
  },
  {
    path: 'registro',
    component: Registro,
    canActivate: [guestGuard],
  },
  {
    path: 'dashboard',
    component: Dashboard,
    canActivate: [authGuard],
  },
  {
    path: 'analisis-proyecto',
    component: AnalisisProyecto,
    canActivate: [authGuard],
  },
  {
    path: 'historial-proyectos',
    component: HistorialProyectos,
    canActivate: [authGuard],
  },
  {
    path: 'documentacion/:id',
    component: VerDocumentacion,
    canActivate: [authGuard],
  },
];
