import type { User } from '../../../types';
import type { AssigneeRecommendation, AgentRecommendation } from '../../../api';
import type { EditDefectForm } from '../types';
import type { ManualFixForm } from './ManualFixCompleteModal';
import AssignModal from './AssignModal';
import AnalyzeModal from './AnalyzeModal';
import FixTaskModal from './FixTaskModal';
import ManualFixCompleteModal from './ManualFixCompleteModal';
import EditDefectModal from './EditDefectModal';
import RejectModal from './RejectModal';
import '../defect-detail.css';

interface DefectModalsProps {
  assignModalOpen: boolean;
  selectedAssignee: number | null;
  assigneeRecommendations: AssigneeRecommendation[];
  assigneeRecommendLoading: boolean;
  users: User[];
  onAssignModalCancel: () => void;
  onAssignModalOk: () => void;
  onSelectedAssigneeChange: (value: number | null) => void;

  analyzeModalOpen: boolean;
  selectedAgentTypes: string[];
  agentRecommendations: AgentRecommendation[];
  agentRecommendLoading: boolean;
  onAnalyzeModalCancel: () => void;
  onAnalyzeModalOk: () => void;
  onSelectedAgentTypesChange: (values: string[]) => void;

  fixModalOpen: boolean;
  fixBranch: string;
  onFixModalCancel: () => void;
  onFixModalOk: () => void;
  onFixBranchChange: (value: string) => void;

  manualFixCompleteOpen: boolean;
  manualFixForm: ManualFixForm;
  onManualFixCompleteCancel: () => void;
  onManualFixCompleteOk: () => void;
  onManualFixFormChange: (form: ManualFixForm) => void;

  editModalOpen: boolean;
  editForm: EditDefectForm;
  onEditModalCancel: () => void;
  onEditModalOk: () => void;
  onEditFormChange: (form: EditDefectForm) => void;

  rejectModalOpen: boolean;
  rejectReason: string;
  onRejectModalCancel: () => void;
  onRejectModalOk: () => void;
  onRejectReasonChange: (value: string) => void;
}

export default function DefectModals({
  assignModalOpen,
  selectedAssignee,
  assigneeRecommendations,
  assigneeRecommendLoading,
  users,
  onAssignModalCancel,
  onAssignModalOk,
  onSelectedAssigneeChange,

  analyzeModalOpen,
  selectedAgentTypes,
  agentRecommendations,
  agentRecommendLoading,
  onAnalyzeModalCancel,
  onAnalyzeModalOk,
  onSelectedAgentTypesChange,

  fixModalOpen,
  fixBranch,
  onFixModalCancel,
  onFixModalOk,
  onFixBranchChange,

  manualFixCompleteOpen,
  manualFixForm,
  onManualFixCompleteCancel,
  onManualFixCompleteOk,
  onManualFixFormChange,

  editModalOpen,
  editForm,
  onEditModalCancel,
  onEditModalOk,
  onEditFormChange,

  rejectModalOpen,
  rejectReason,
  onRejectModalCancel,
  onRejectModalOk,
  onRejectReasonChange,
}: DefectModalsProps) {
  return (
    <>
      <AssignModal
        open={assignModalOpen}
        onCancel={onAssignModalCancel}
        onOk={onAssignModalOk}
        users={users}
        selectedAssignee={selectedAssignee}
        onSelectedAssigneeChange={onSelectedAssigneeChange}
        assigneeRecommendations={assigneeRecommendations}
        assigneeRecommendLoading={assigneeRecommendLoading}
      />
      <AnalyzeModal
        open={analyzeModalOpen}
        onCancel={onAnalyzeModalCancel}
        onOk={onAnalyzeModalOk}
        selectedAgentTypes={selectedAgentTypes}
        onSelectedAgentTypesChange={onSelectedAgentTypesChange}
        agentRecommendations={agentRecommendations}
        agentRecommendLoading={agentRecommendLoading}
      />
      <FixTaskModal
        open={fixModalOpen}
        onCancel={onFixModalCancel}
        onOk={onFixModalOk}
        fixBranch={fixBranch}
        onFixBranchChange={onFixBranchChange}
      />
      <ManualFixCompleteModal
        open={manualFixCompleteOpen}
        onCancel={onManualFixCompleteCancel}
        onOk={onManualFixCompleteOk}
        form={manualFixForm}
        onFormChange={onManualFixFormChange}
      />
      <EditDefectModal
        open={editModalOpen}
        onCancel={onEditModalCancel}
        onOk={onEditModalOk}
        form={editForm}
        onFormChange={onEditFormChange}
      />
      <RejectModal
        open={rejectModalOpen}
        onCancel={onRejectModalCancel}
        onOk={onRejectModalOk}
        rejectReason={rejectReason}
        onRejectReasonChange={onRejectReasonChange}
      />
    </>
  );
}
