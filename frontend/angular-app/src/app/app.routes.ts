import { Routes } from '@angular/router';
import { Login } from './paginas/login/login';
import { Registro } from './paginas/registro/registro';
import { Dashboard } from './paginas/dashboard/dashboard';
import { AnalisisProyecto } from './paginas/analisis-proyecto/analisis-proyecto';
import { HistorialProyectos } from './paginas/historial-proyectos/historial-proyectos';
import { RevisionC4 } from './paginas/revision-c4/revision-c4';
import { ResultadoC4 } from './paginas/resultado-c4/resultado-c4';
import { ExploradorC4Pagina } from './componentes/explorador-c4/explorador-c4';
import { authGuard } from './guards/auth.guard';
import { guestGuard } from './guards/guest.guard';
import { AppShell } from './componentes/app-shell/app-shell';

export const routes: Routes = [
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
    path: '',
    component: AppShell,
    canActivate: [authGuard],
    children: [
      { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
      { path: 'dashboard', component: Dashboard },
      { path: 'analisis-proyecto', component: AnalisisProyecto },
      { path: 'historial-proyectos', component: HistorialProyectos },
      { path: 'c4/:idRepositorio/ejecuciones/:idEjecucion/revision', component: RevisionC4 },
      { path: 'c4/:idRepositorio/ejecuciones/:idEjecucion/resultado', component: ResultadoC4 },
      { path: 'c4/:idRepositorio/ejecuciones/:idEjecucion/explorador', component: ExploradorC4Pagina },
    ],
  },
];
