import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import {
  LucideArrowRight,
  LucideBookOpenCheck,
  LucideBoxes,
  LucideGitBranch,
  LucideHistory,
  LucideScanSearch,
  LucideSparkles,
} from '@lucide/angular';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    RouterLink,
    LucideArrowRight,
    LucideBookOpenCheck,
    LucideBoxes,
    LucideGitBranch,
    LucideHistory,
    LucideScanSearch,
    LucideSparkles,
  ],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard {}
